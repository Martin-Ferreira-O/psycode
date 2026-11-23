import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime
from functools import partial
from uuid import UUID, uuid4
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import OperationalError, close_old_connections, connections, transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from backend.apps.agenda.collector_check import CAPABILITY as SMILE_CHECK_CAPABILITY, sources_for
from backend.apps.operational.smile_configuration import CAPABILITY as SMILE_CONFIG_CAPABILITY
from backend.common.audit import AuditWriter
from backend.common.errors import ServiceError
from . import leases, chunk_config
from .authentication import authenticate_agent_header, ensure_agent_identity_current
from .domain import CaptureError, TECHNICAL_ERRORS
from .models import (
    AgentCommand,
    AgentRegistration,
    AgentStatus,
    CaptureSession,
    OPEN_STATES,
    RuntimeLease,
    AgentConfiguration,
    ConfigurationState,
)
from .protocol import MAX_BYTES, decode, envelope, identifier, instant, configuration, CONFIG_ERRORS, CONFIG_KEYS
from .server_connectivity import (
    reconcile_connection,
    register_server_disconnect,
    register_server_reconnect,
)
from .services import CaptureSessionService, _snapshot


CONFIG_CAPABILITY = "agent.config.v1"
YIELD_REPLACED_CAPABILITY = "control.yield-replaced.v1"
MAX_COMMAND_BATCH = 16
SEND_TIMEOUT = 5


class ConfigurationConflict(ValueError):
    def __init__(self, applied, local):
        super().__init__("CONFIG_VERSION_CONFLICT")
        self.effective = {
            "version": applied.version if applied else 0,
            "local_revision": local.local_revision if local else 0,
            "effective_config": configuration(applied.effective_config, effective=True) if applied else {},
            "source": applied.source if applied else None,
        }


def lease_ttl():
    return max(30, settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS + SEND_TIMEOUT)


def serial(value):
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError("Unserializable")


def payload(value):
    return json.loads(json.dumps(asdict(value), default=serial))


def database_call(fn, *args):
    close_old_connections()
    try:
        return fn(*args)
    finally:
        connections.close_all()


async def db(fn, *args):
    return await sync_to_async(database_call, thread_sensitive=False)(fn, *args)


class RemoteControl:
    def __init__(self, identity, owner):
        self.identity, self.owner = identity, owner
        self.name = "control:" + identity.box
        self.service = CaptureSessionService()
        self.yield_replaced = False
        self.chunk_config_supported = False
        self.chunk_config_v2_supported = False
        self.config_supported = False

    def _lock_identity(self):
        if self.identity.managed:
            AgentRegistration.objects.select_for_update().filter(pk=self.identity.registry_id).first()
        ensure_agent_identity_current(self.identity)

    def _lock_lease(self):
        lease = RuntimeLease.objects.select_for_update().filter(name=self.name).first()
        if lease is None or not leases.owned(self.name, self.owner):
            raise ValueError("CONNECTION_REPLACED")

    def open(self):
        with transaction.atomic():
            if self.identity.managed:
                agent = AgentRegistration.objects.select_for_update().get(pk=self.identity.registry_id)
                if agent.control_owner:
                    reconcile_connection(agent)
            ensure_agent_identity_current(self.identity)
            acquired = leases.acquire(self.name, self.owner, ttl=lease_ttl(), replace=not self.yield_replaced)
            if acquired and self.identity.managed:
                AgentRegistration.objects.filter(pk=self.identity.registry_id).update(control_owner=self.owner)
            return acquired

    def close(self, cause="UNKNOWN"):
        with transaction.atomic():
            if self.identity.managed:
                agent = AgentRegistration.objects.select_for_update().get(pk=self.identity.registry_id)
                if agent.control_owner == self.owner:
                    register_server_disconnect(self.identity, cause=cause)
                    AgentRegistration.objects.filter(pk=agent.pk).update(control_owner=None)
            leases.release(self.name, self.owner)

    @transaction.atomic
    def register_hello(self, agent_version, smile_check_supported=False, smile_config_supported=False):
        self._lock_identity()
        self._lock_lease()
        now = timezone.now()
        status, _ = AgentStatus.objects.get_or_create(
            box=self.identity.box,
            defaults={"seen_at": now, "diagnostics": {}},
        )
        previous = AgentRegistration.objects.filter(pk=self.identity.registry_id).values_list(
            "diagnostics", flat=True
        ).first() if self.identity.managed else {}
        diagnostics = {**(previous or {}), "agent_version": agent_version}
        for key in ("smile_check_supported", "smile_config_supported"):
            diagnostics.pop(key, None)
        if smile_check_supported:
            diagnostics["smile_check_supported"] = True
        if smile_config_supported:
            diagnostics["smile_config_supported"] = True
        status.seen_at = now
        status.diagnostics = diagnostics
        status.save(update_fields=["seen_at", "diagnostics"])
        if self.identity.managed:
            AgentRegistration.objects.filter(pk=self.identity.registry_id).update(
                last_seen_at=now,
                diagnostics=diagnostics,
            )

    def mark_config_received(self, config_id):
        config = AgentConfiguration.objects.select_for_update().filter(
            config_id=config_id, agent_id=self.identity.registry_id
        ).first()
        if not config:
            raise ValueError("CONFIG_NOT_FOUND")
        if config.state == ConfigurationState.PENDING:
            config.state = ConfigurationState.RECEIVED
            config.save(update_fields=["state", "updated_at"])
            AuditWriter.emit(
                {
                    "event_id": str(uuid4()),
                    "timestamp": timezone.now().isoformat(),
                    "action": "capture.agent_config.received",
                    "outcome": "success",
                    "agent_id": str(self.identity.registry_id),
                    "box": self.identity.box,
                    "config_id": str(config.pk),
                    "version": config.version,
                    "state": config.state,
                }
            )
        return config

    def acknowledge_config(self, config_id, success=None, effective_config=None, error_code="", received_only=False):
        config = AgentConfiguration.objects.select_for_update().filter(
            config_id=config_id, agent_id=self.identity.registry_id
        ).first()
        if not config:
            raise ValueError("CONFIG_NOT_FOUND")

        if config.state not in [ConfigurationState.PENDING, ConfigurationState.RECEIVED]:
            return config

        latest_applied = AgentConfiguration.objects.filter(
            agent_id=self.identity.registry_id,
            state=ConfigurationState.APPLIED,
        ).order_by("-version").first()

        if latest_applied and config.version <= latest_applied.version:
            config.state = ConfigurationState.FAILED
            config.error_code = "OBSOLETE_VERSION_REJECTED"
            if not config.effective_config and latest_applied.effective_config:
                config.effective_config = configuration(latest_applied.effective_config, effective=True)
            config.save(update_fields=["state", "effective_config", "error_code", "updated_at"])
            AuditWriter.emit(
                {
                    "event_id": str(uuid4()),
                    "timestamp": timezone.now().isoformat(),
                    "action": "capture.agent_config.obsolete_rejected",
                    "outcome": "failure",
                    "agent_id": str(self.identity.registry_id),
                    "box": self.identity.box,
                    "config_id": str(config.pk),
                    "version": config.version,
                    "state": config.state,
                    "error_code": config.error_code,
                }
            )
            return config

        if config.state == ConfigurationState.PENDING:
            config.state = ConfigurationState.RECEIVED
            config.save(update_fields=["state", "updated_at"])

        if received_only or success is None:
            return config

        error_code = error_code if isinstance(error_code, str) and (not error_code or error_code in CONFIG_ERRORS) else "CONFIG_APPLY_FAILED"
        if effective_config is not None:
            try:
                effective_config = configuration(effective_config, effective=True)
            except ValueError:
                effective_config, success, error_code = None, False, "INVALID_EFFECTIVE_CONFIG"

        if success:
            if not isinstance(effective_config, dict) or (config.desired_config and not effective_config):
                success = False
                error_code = error_code or "MISSING_EFFECTIVE_CONFIG"
            elif any(effective_config.get(key) != value for key, value in config.desired_config.items()):
                success, error_code = False, "INVALID_EFFECTIVE_CONFIG"

        if success:
            config.state = ConfigurationState.APPLIED
            config.effective_config = effective_config
            config.error_code = ""
            config.save(update_fields=["state", "effective_config", "error_code", "updated_at"])

            older_pending = AgentConfiguration.objects.filter(
                agent_id=self.identity.registry_id,
                version__lt=config.version,
                state__in=[ConfigurationState.PENDING, ConfigurationState.RECEIVED],
            )
            for older in older_pending:
                older.state = ConfigurationState.FAILED
                older.error_code = "SUPERSEDED_BY_NEWER_VERSION"
                if not older.effective_config:
                    older.effective_config = config.effective_config
                older.save(update_fields=["state", "effective_config", "error_code", "updated_at"])
        else:
            config.state = ConfigurationState.FAILED
            config.error_code = error_code or "CONFIG_APPLY_FAILED"
            if latest_applied:
                config.effective_config = configuration(latest_applied.effective_config, effective=True)
            config.save(update_fields=["state", "effective_config", "error_code", "updated_at"])

        AuditWriter.emit(
            {
                "event_id": str(uuid4()),
                "timestamp": timezone.now().isoformat(),
                "action": "capture.agent_config.acknowledged",
                "outcome": "success" if success else "failure",
                "agent_id": str(self.identity.registry_id),
                "box": self.identity.box,
                "config_id": str(config.pk),
                "version": config.version,
                "state": config.state,
                "error_code": config.error_code or None,
            }
        )
        return config

    def local_configuration(self, data):
        if not self.config_supported or not self.identity.managed or set(data) != {"base_version", "local_revision", "effective_config"}:
            raise ValueError("INVALID_MESSAGE")
        if any(type(data[k]) is not int or not 0 <= data[k] <= 9223372036854775806
               for k in ("base_version", "local_revision")):
            raise ValueError("INVALID_MESSAGE")
        effective = configuration(data["effective_config"], effective=True)
        if effective.keys() != CONFIG_KEYS:
            raise ValueError("INVALID_CONFIGURATION")
        configs = AgentConfiguration.objects.filter(agent_id=self.identity.registry_id)
        latest = configs.order_by("-version").first()
        local = configs.filter(source="local").order_by("-version").first()
        applied = configs.filter(state=ConfigurationState.APPLIED).order_by("-version").first()
        revision = data["local_revision"]
        base_version = data["base_version"]
        if base_version > (latest.version if latest else 0):
            raise ConfigurationConflict(applied, local)
        if local and revision < local.local_revision:
            raise ConfigurationConflict(applied, local)
        if local and revision == local.local_revision:
            if applied and (
                effective != configuration(applied.effective_config, effective=True)
                or (base_version < applied.version and effective != configuration(local.effective_config, effective=True))
            ):
                raise ConfigurationConflict(applied, local)
            return {"version": applied.version if applied else 0, "local_revision": revision}
        if applied and base_version < applied.version:
            raise ConfigurationConflict(applied, local)
        # The first report records the initial baseline at revision zero. It
        # must not obsolete a web request already waiting for that baseline.
        initial = local is None and revision == 0 and applied is None
        for pending in configs.filter(state__in=[ConfigurationState.PENDING, ConfigurationState.RECEIVED]):
            if pending.local_revision != revision:
                pending.state, pending.error_code = ConfigurationState.FAILED, "CONFIG_VERSION_CONFLICT"
                pending.save(update_fields=["state", "error_code", "updated_at"])
                AuditWriter.emit({"event_id": str(uuid4()), "timestamp": timezone.now().isoformat(),
                    "action": "capture.agent_config.conflict", "outcome": "failure",
                    "actor_id": self.identity.registry_id, "agent_id": self.identity.registry_id,
                    "box": self.identity.box, "config_id": str(pending.pk), "version": pending.version,
                    "local_revision": revision, "error_code": pending.error_code})
        version = 0 if initial else (latest.version + 1 if latest else 0)
        row = configs.create(agent_id=self.identity.registry_id, version=version, source="local", local_revision=revision,
            desired_config=effective, effective_config=effective, state=ConfigurationState.APPLIED)
        AuditWriter.emit({"event_id": str(uuid4()), "timestamp": timezone.now().isoformat(),
            "action": "capture.agent_config.local", "outcome": "success", "actor_id": self.identity.registry_id,
            "agent_id": self.identity.registry_id, "box": self.identity.box,
            "config_id": str(row.pk), "version": version, "local_revision": revision, "state": row.state})
        return {"version": row.version, "local_revision": revision}

    def poll_configs(self):
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            latest_applied = AgentConfiguration.objects.filter(
                agent_id=self.identity.registry_id,
                state=ConfigurationState.APPLIED,
            ).order_by("-version").first()
            configs = AgentConfiguration.objects.filter(
                agent_id=self.identity.registry_id,
                state__in=[ConfigurationState.PENDING, ConfigurationState.RECEIVED],
            )
            if latest_applied:
                configs = configs.filter(version__gt=latest_applied.version)
            latest_pending = configs.order_by("-version").first()
            if not latest_pending:
                return []
            return [
                {
                    "config_id": str(latest_pending.config_id),
                    "version": latest_pending.version,
                    "desired_config": latest_pending.desired_config,
                    "base_local_revision": latest_pending.local_revision,
                }
            ]

    def dispatch(self, message):
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            box, p, kind = self.identity.box, message["payload"], message["type"]
            if "box" in p and p["box"] != box:
                raise ValueError("BOX_FORBIDDEN")

            if kind == "config_local":
                return "config_receipt", self.local_configuration(p)

            if kind == "config_received":
                if "config_id" not in p or p.keys() - {"config_id", "box"}:
                    raise ValueError("INVALID_MESSAGE")
                cid = identifier(p["config_id"])
                result = self.mark_config_received(cid)
                return "config_receipt", {"config_id": str(cid), "state": result.state}

            if kind == "config_ack":
                if "config_id" not in p:
                    raise ValueError("INVALID_MESSAGE")
                allowed = {"config_id", "success", "state", "effective_config", "error_code", "box", "local_revision"}
                if p.keys() - allowed:
                    raise ValueError("INVALID_MESSAGE")
                cid = identifier(p["config_id"])

                if "state" in p and (not isinstance(p["state"], str) or p["state"] not in {ConfigurationState.RECEIVED, "received"}):
                    raise ValueError("INVALID_MESSAGE")
                if "state" in p and "success" not in p:
                    result = self.acknowledge_config(cid, received_only=True)
                    return "config_receipt", {"config_id": str(cid), "state": result.state}

                if "success" not in p or type(p["success"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                if "local_revision" in p:
                    if type(p["local_revision"]) is not int or p["local_revision"] < 0:
                        raise ValueError("INVALID_MESSAGE")
                    config = AgentConfiguration.objects.filter(pk=cid, agent_id=self.identity.registry_id).first()
                    local = AgentConfiguration.objects.filter(agent_id=self.identity.registry_id, source="local").order_by("-version").first()
                    if config and (p["local_revision"] != config.local_revision
                            or (local and local.local_revision != config.local_revision)):
                        p = {**p, "success": False, "error_code": "CONFIG_VERSION_CONFLICT"}

                result = self.acknowledge_config(
                    cid,
                    success=p["success"],
                    effective_config=p.get("effective_config"),
                    error_code=p.get("error_code", ""),
                )
                return "config_receipt", {"config_id": str(cid), "state": result.state}

            if kind == "sync":
                commands = self.commands()
                sessions = CaptureSession.objects.filter(
                    box=box, state__in=OPEN_STATES, actual_end__isnull=True
                ).order_by("authorized_at", "pk")[:MAX_COMMAND_BATCH]
                leases.acquire(self.name, self.owner, ttl=lease_ttl())
                register_server_reconnect(self.identity)
                return "state", {
                    "sessions": [payload(_snapshot(s)) for s in sessions],
                    "commands": commands,
                }
            if kind == "command_ack":
                required = {"command_id", "session_id", "success", "occurred_at"}
                if not required <= p.keys() or p.keys() - required - {"last_sequence", "error_code"}:
                    raise ValueError("INVALID_MESSAGE")
                cid, sid = identifier(p["command_id"]), identifier(p["session_id"])
                if type(p["success"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                if not AgentCommand.objects.filter(pk=cid, session_id=sid, session__box=box).exists():
                    raise ValueError("COMMAND_NOT_FOUND")
                result = self.service.acknowledge(
                    box,
                    cid,
                    success=p["success"],
                    occurred_at=instant(p["occurred_at"]),
                    last_sequence=p.get("last_sequence"),
                    error_code=p.get("error_code", ""),
                )
                return "command_receipt", {"command_id": str(cid), "session": payload(result)}
            if kind in {"heartbeat", "interrupted"}:
                if p.keys() - {"session_id", "error_code"}:
                    raise ValueError("INVALID_MESSAGE")
                sid = identifier(p["session_id"])
                if kind == "heartbeat":
                    result = self.service.heartbeat(box, sid)
                    return "heartbeat_receipt", {"session": payload(result)}
                code = p.get("error_code", "AGENT_INTERRUPTED")
                if code not in TECHNICAL_ERRORS:
                    raise ValueError("INVALID_TECHNICAL_ERROR")
                return "interruption_receipt", {"session": payload(self.service.interrupted(box, sid, error_code=code))}
            if kind == "status":
                allowed = {
                    "obs",
                    "capturing",
                    "pending",
                    "free_bytes",
                    "remaining_seconds",
                    "smile_last_sync",
                    "operational_code",
                }
                if p.keys() - allowed or len(json.dumps(p)) > 2048:
                    raise ValueError("INVALID_MESSAGE")
                for key in ("pending", "free_bytes", "remaining_seconds"):
                    if key in p and (type(p[key]) is not int or p[key] < 0):
                        raise ValueError("INVALID_MESSAGE")
                if p.get("obs", "unknown") not in {"unknown", "ready", "busy", "unavailable"}:
                    raise ValueError("INVALID_MESSAGE")
                if "capturing" in p and type(p["capturing"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                if p.get("operational_code", "") not in {
                    "",
                    "RECOVERY_REQUIRED",
                    "DISK_LOW",
                    "STORAGE_WARNING",
                    "STORAGE_CRITICAL",
                    "UPLOAD_INTERVENTION",
                    "SMILE_UNAVAILABLE",
                }:
                    raise ValueError("INVALID_MESSAGE")
                if p.get("smile_last_sync") is not None:
                    instant(p["smile_last_sync"])
                status, _ = AgentStatus.objects.get_or_create(
                    box=box,
                    defaults={"seen_at": timezone.now(), "diagnostics": {}},
                )
                diagnostics = {"agent_version": status.diagnostics.get("agent_version")}
                for key in ("smile_check_supported", "smile_config_supported"):
                    if status.diagnostics.get(key) is True:
                        diagnostics[key] = True
                diagnostics.update(p)
                status.seen_at = timezone.now()
                diagnostics["status_reported_at"] = status.seen_at.isoformat()
                status.diagnostics = diagnostics
                status.save(update_fields=["seen_at", "diagnostics"])
                if self.identity.managed:
                    AgentRegistration.objects.filter(pk=self.identity.registry_id).update(
                        last_seen_at=status.seen_at,
                        diagnostics=diagnostics,
                    )
                leases.acquire(self.name, self.owner, ttl=lease_ttl())
                register_server_reconnect(self.identity)
                return "state", {"status_persisted": True}
            raise ValueError("INVALID_MESSAGE")

    def command_payload(self, command):
        data = payload(command)
        if not self.chunk_config_supported or command.kind != "inicio" or command.audio_chunk_duration is None:
            data.pop("audio_chunk_duration", None)
        if command.kind != "inicio" or command.audio_chunk_overlap is None:
            data.pop("audio_chunk_overlap", None)
        return data

    def commands(self):
        pending = None
        if self.config_supported:
            rows = AgentConfiguration.objects.filter(agent_id=self.identity.registry_id)
            pending = rows.filter(state__in=[ConfigurationState.PENDING, ConfigurationState.RECEIVED]).exists()
        return [
            self.command_payload(c)
            for c in self.service.commands(
                self.identity.box,
                chunk_config_supported=self.chunk_config_supported,
                chunk_config_v2_supported=self.chunk_config_v2_supported,
                limit=MAX_COMMAND_BATCH,
                redelivery_seconds=15,
                configuration_pending=bool(pending),
            )
        ]

    def poll(self):
        ensure_agent_identity_current(self.identity)
        if not leases.owned(self.name, self.owner):
            raise ValueError("CONNECTION_REPLACED")
        if not CaptureSession.objects.filter(
            box=self.identity.box, state__in=OPEN_STATES, actual_end__isnull=True
        ).exists():
            pending_stop = AgentCommand.objects.filter(
                session__box=self.identity.box,
                session__actual_end__isnull=True,
                kind="detencion",
                cancelled_at=None,
            ).exclude(succeeded=True)
            if not pending_stop.exists():
                return []
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            return self.commands()

    def still_current(self, command):
        ensure_agent_identity_current(self.identity)
        if not leases.owned(self.name, self.owner):
            raise ValueError("CONNECTION_REPLACED")
        candidates = AgentCommand.objects.filter(pk=command["command_id"], cancelled_at=None).exclude(succeeded=True)
        if command["kind"] == "inicio":
            candidates = candidates.filter(
                acknowledged_at=None,
                session__scheduled_end__gt=timezone.now(),
                session__authorization_ended_at=None,
            )
        elif command["kind"] == "detencion":
            candidates = candidates.filter(session__actual_end=None)
        return candidates.exists()


async def agent_websocket(scope, receive, send):
    event = await receive()
    if event["type"] != "websocket.connect":
        return

    async def send_bounded(event):
        await asyncio.wait_for(send(event), timeout=SEND_TIMEOUT)

    async def deny(status, code, close_code, retry_after=None):
        if "websocket.http.response" not in scope.get("extensions", {}):
            await send_bounded({"type": "websocket.close", "code": close_code})
            return
        response_headers = [(b"x-psycode-control-error", code.encode("ascii"))]
        if retry_after is not None:
            response_headers.append((b"retry-after", str(retry_after).encode("ascii")))
        await send_bounded(
            {
                "type": "websocket.http.response.start",
                "status": status,
                "headers": response_headers,
            }
        )
        await send_bounded({"type": "websocket.http.response.body", "body": b""})

    if scope["path"] != "/ws/v1/agents":
        await deny(404, "ROUTE_NOT_FOUND", 4404)
        return
    headers = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
    try:
        if len(headers) != 1 or scope.get("query_string"):
            raise AuthenticationFailed()
        client = scope.get("client")
        source_ip = client[0] if client else ""
        identity = await db(partial(authenticate_agent_header, headers[0], source_ip=source_ip))
    except AuthenticationFailed:
        await deny(401, "CREDENTIAL_INVALID", 4401)
        return
    except ServiceError as exc:
        if exc.code == "AUTH_RATE_LIMITED":
            await deny(429, "AUTH_RATE_LIMITED", 4429, settings.CAPTURE_AGENT_AUTH_WINDOW_SECONDS)
            return
        raise
    except OperationalError:
        await deny(503, "DATABASE_UNAVAILABLE", 1013)
        return

    await send_bounded({"type": "websocket.accept"})
    control = RemoteControl(identity, uuid4())
    acquisition = None
    pending = None
    disconnect_cause = "UNKNOWN"

    async def emit(kind, data, correlation=None):
        raw = json.dumps(envelope(kind, data, correlation), default=serial, separators=(",", ":"))
        if len(raw.encode()) > MAX_BYTES:
            raise ValueError("MESSAGE_TOO_LARGE")
        await send_bounded({"type": "websocket.send", "text": raw})

    try:
        event = await asyncio.wait_for(receive(), timeout=10)
        hello = decode(event.get("text"))
        p = hello["payload"]
        if (
            hello["type"] != "hello"
            or set(p) != {"agent_version", "capabilities"}
            or not isinstance(p["agent_version"], str)
            or len(p["agent_version"]) > 64
            or not isinstance(p["capabilities"], list)
            or len(p["capabilities"]) > 16
            or any(not isinstance(x, str) or len(x) > 64 for x in p["capabilities"])
        ):
            raise ValueError("INVALID_MESSAGE")
        control.yield_replaced = YIELD_REPLACED_CAPABILITY in p["capabilities"]
        acquisition = asyncio.create_task(db(control.open))
        if not await asyncio.shield(acquisition):
            raise ValueError("CONNECTION_REPLACED")
        smile_config = SMILE_CONFIG_CAPABILITY in p["capabilities"]
        smile_check = SMILE_CHECK_CAPABILITY in p["capabilities"] and (
            smile_config or bool(await db(sources_for, identity))
        )
        config_supported = identity.managed and CONFIG_CAPABILITY in p["capabilities"]
        control.config_supported = config_supported
        control.chunk_config_v2_supported = {chunk_config.CAPABILITY_V2, "audio.v2"} <= set(p["capabilities"])
        control.chunk_config_supported = (
            control.chunk_config_v2_supported or {chunk_config.CAPABILITY, "audio.v2"} <= set(p["capabilities"])
        )
        await db(control.register_hello, p["agent_version"], smile_check, smile_config)
        capabilities = [
            "audio.v2",
            "agenda.excel.v1",
            "agenda.smile-json.v1",
            "agent.events.v1",
            "sessions.capture-ended.v1",
        ]
        if control.chunk_config_supported:
            capabilities.append(chunk_config.CAPABILITY)
        if control.chunk_config_v2_supported:
            capabilities.append(chunk_config.CAPABILITY_V2)
        if smile_check:
            capabilities.append(SMILE_CHECK_CAPABILITY)
        if smile_config:
            capabilities.append(SMILE_CONFIG_CAPABILITY)
        if config_supported:
            capabilities.append(CONFIG_CAPABILITY)
        await emit(
            "ready",
            {
                "box": identity.box,
                "server_time": timezone.now().isoformat(),
                "capabilities": capabilities,
                "heartbeat_interval": settings.CAPTURE_HEARTBEAT_SECONDS,
            },
            hello["message_id"],
        )
        next_poll = 0
        last_message = time.monotonic()
        pending = asyncio.create_task(receive())
        batch = []
        while True:
            deadline = last_message + settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS
            if time.monotonic() >= deadline:
                disconnect_cause = "CONNECTION_TIMEOUT"
                await send_bounded({"type": "websocket.close", "code": 4408})
                break
            if pending.done():
                event = pending.result()
                if event["type"] == "websocket.disconnect":
                    break
                pending = asyncio.create_task(receive())
                message = decode(event.get("text"))
                try:
                    kind, data = await db(control.dispatch, message)
                except CaptureError as exc:
                    await emit("error", {"code": exc.code, "recoverable": False}, message["message_id"])
                except ConfigurationConflict as exc:
                    await emit("error", {"code": str(exc), "recoverable": False,
                        "configuration": exc.effective}, message["message_id"])
                except ValueError as exc:
                    if str(exc) == "CONNECTION_REPLACED":
                        raise
                    code = (
                        str(exc)
                        if str(exc)
                        in {
                            "COMMAND_NOT_FOUND",
                            "BOX_FORBIDDEN",
                            "CONFIG_NOT_FOUND",
                            "INVALID_TECHNICAL_ERROR",
                            "CONFIG_VERSION_CONFLICT",
                        }
                        else "INVALID_MESSAGE"
                    )
                    await emit("error", {"code": code, "recoverable": False}, message["message_id"])
                except OperationalError:
                    await emit("error", {"code": "DATABASE_UNAVAILABLE", "recoverable": True}, message["message_id"])
                else:
                    last_message = time.monotonic()
                    await emit(kind, data, message["message_id"])
                continue
            if batch:
                kind, data = batch.pop(0)
                if kind != "command" or await db(control.still_current, data):
                    await emit(kind, data)
                continue
            if time.monotonic() >= next_poll:
                batch = [("command", item) for item in await db(control.poll)]
                if config_supported:
                    batch.extend(("config_sync", item) for item in await db(control.poll_configs))
                next_poll = time.monotonic() + settings.CAPTURE_COMMAND_INTERVAL_SECONDS
                continue
            await asyncio.wait([pending], timeout=max(0, min(next_poll, deadline) - time.monotonic()))

    except AuthenticationFailed:
        disconnect_cause = "CREDENTIAL_INVALIDATED"
        await send_bounded({"type": "websocket.close", "code": 4401})
    except (TimeoutError, OSError, OperationalError):
        disconnect_cause = "CONNECTION_TIMEOUT"
        try:
            await send_bounded({"type": "websocket.close", "code": 1013})
        except (OSError, TimeoutError):
            pass
    except (ValueError, KeyError, TypeError) as exc:
        allowed_codes = {"PROTOCOL_INCOMPATIBLE", "CONNECTION_REPLACED", "MESSAGE_TOO_LARGE"}
        code = str(exc) if str(exc) in allowed_codes else "INVALID_MESSAGE"
        await emit("error", {"code": code, "recoverable": code == "CONNECTION_REPLACED"})
        await send_bounded({"type": "websocket.close", "code": 4409 if code == "CONNECTION_REPLACED" else 4406})
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if acquisition is not None:
            await asyncio.gather(acquisition, return_exceptions=True)
            try:
                await db(control.close, disconnect_cause)
            except OperationalError:
                pass
