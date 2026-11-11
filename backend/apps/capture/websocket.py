"""Adaptador ASGI: el dominio conserva órdenes, sesiones y ACK en SQL."""
import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid4
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from .authentication import (authenticate_agent_header,ensure_agent_identity_current,)
from .domain import CaptureError, TECHNICAL_ERRORS
from .models import AgentCommand, AgentRegistration, AgentStatus, CaptureSession, OPEN_STATES, RuntimeLease, AgentConfiguration, ConfigurationState
from .services import CaptureSessionService, _snapshot
from .protocol import MAX_BYTES, decode, envelope, identifier, instant
from . import leases
from .server_connectivity import (
    reconcile_connection,
    register_server_disconnect,
    register_server_reconnect,
)
from functools import partial
from backend.common.errors import ServiceError
from backend.apps.agenda.collector_check import CAPABILITY as SMILE_CHECK_CAPABILITY, sources_for


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
        close_old_connections()


async def db(fn, *args):
    return await sync_to_async(database_call, thread_sensitive=True)(fn, *args)


class RemoteControl:
    def __init__(self, identity, owner):
        self.identity, self.owner = identity, owner
        self.name = "control:" + identity.box
        self.service = CaptureSessionService()

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
            acquired = leases.acquire(self.name, self.owner, replace=True)
            if self.identity.managed:
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
    def register_hello(self, agent_version, smile_check_supported=False):
        self._lock_identity()
        self._lock_lease()
        now = timezone.now()
        status, _ = AgentStatus.objects.get_or_create(
            box=self.identity.box,
            defaults={"seen_at": now, "diagnostics": {}},
        )
        diagnostics = {"agent_version": agent_version}
        if smile_check_supported:
            diagnostics["smile_check_supported"] = True
        status.seen_at = now
        status.diagnostics = diagnostics
        status.save(update_fields=["seen_at", "diagnostics"])
        if self.identity.managed:
            AgentRegistration.objects.filter(pk=self.identity.registry_id).update(
                last_seen_at=now, diagnostics=diagnostics,
            )

    def acknowledge_config(self, config_id, success, effective_config=None, error_code=""):
        config = AgentConfiguration.objects.filter(config_id=config_id, agent_id=self.identity.registry_id).first()
        if not config:
            raise ValueError("CONFIG_NOT_FOUND")
        if config.state != ConfigurationState.PENDING:
            return config
        config.state = ConfigurationState.APPLIED if success else ConfigurationState.FAILED
        if effective_config is not None:
            config.effective_config = effective_config
        config.error_code = error_code
        config.save(update_fields=["state", "effective_config", "error_code", "updated_at"])
        return config

    def poll_configs(self):
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            leases.acquire(self.name, self.owner)
            configs = AgentConfiguration.objects.filter(
                agent_id=self.identity.registry_id,
                state=ConfigurationState.PENDING
            ).order_by('version')
            return [{"config_id": str(c.config_id), "version": c.version, "desired_config": c.desired_config} for c in configs]

    def dispatch(self, message):
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            leases.acquire(self.name, self.owner)
            box, p, kind = self.identity.box, message["payload"], message["type"]
            if "box" in p and p["box"] != box:
                raise ValueError("BOX_FORBIDDEN")
            
            if kind == "config_ack":
                required = {"config_id", "success"}
                if not required <= p.keys() or p.keys() - required - {"effective_config", "error_code"}:
                    raise ValueError("INVALID_MESSAGE")
                cid = identifier(p["config_id"])
                if type(p["success"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                
                result = self.acknowledge_config(
                    cid,
                    success=p["success"],
                    effective_config=p.get("effective_config"),
                    error_code=p.get("error_code", "")
                )
                return "config_receipt", {"config_id": str(cid), "state": result.state}

            if kind == "sync":
                sessions = CaptureSession.objects.filter(box=box, state__in=OPEN_STATES)
                return "state", {"sessions": [payload(_snapshot(s)) for s in sessions],
                                 "commands": [payload(c) for c in self.service.commands(box)]}
            if kind == "command_ack":
                required = {"command_id", "session_id", "success", "occurred_at"}
                if not required <= p.keys() or p.keys() - required - {"last_sequence", "error_code"}:
                    raise ValueError("INVALID_MESSAGE")
                cid, sid = identifier(p["command_id"]), identifier(p["session_id"])
                if type(p["success"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                if not AgentCommand.objects.filter(pk=cid, session_id=sid, session__box=box).exists():
                    raise ValueError("COMMAND_NOT_FOUND")
                result = self.service.acknowledge(box, cid, success=p["success"],
                    occurred_at=instant(p["occurred_at"]), last_sequence=p.get("last_sequence"),
                    error_code=p.get("error_code", ""))
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
                allowed = {"obs", "capturing", "pending", "free_bytes","remaining_seconds", "smile_last_sync", "operational_code"}
                if p.keys() - allowed or len(json.dumps(p)) > 2048:
                    raise ValueError("INVALID_MESSAGE")
                for key in ("pending", "free_bytes", "remaining_seconds"):
                    if key in p and (type(p[key]) is not int or p[key] < 0):
                        raise ValueError("INVALID_MESSAGE")
                if p.get("obs", "unknown") not in {"unknown", "ready", "busy", "unavailable"}:
                    raise ValueError("INVALID_MESSAGE")
                if "capturing" in p and type(p["capturing"]) is not bool:
                    raise ValueError("INVALID_MESSAGE")
                if p.get("operational_code", "") not in {"", "RECOVERY_REQUIRED", "DISK_LOW","STORAGE_WARNING","STORAGE_CRITICAL", "UPLOAD_INTERVENTION", "SMILE_UNAVAILABLE"}:
                    raise ValueError("INVALID_MESSAGE")
                if p.get("smile_last_sync") is not None:
                    instant(p["smile_last_sync"])
                status, _ = AgentStatus.objects.get_or_create(box=box,defaults={"seen_at": timezone.now(),"diagnostics": {},})
                diagnostics = {"agent_version": status.diagnostics.get("agent_version")}
                if status.diagnostics.get("smile_check_supported") is True:
                    diagnostics["smile_check_supported"] = True
                diagnostics.update(p)
                status.seen_at = timezone.now()
                status.diagnostics = diagnostics
                status.save(update_fields=["seen_at","diagnostics",])
                if self.identity.managed:
                    AgentRegistration.objects.filter(pk=self.identity.registry_id).update(
                        last_seen_at=status.seen_at, diagnostics=diagnostics,
                    )
                return "state", {"status_persisted": True}
            raise ValueError("INVALID_MESSAGE")

    def poll(self):
        with transaction.atomic():
            self._lock_identity()
            self._lock_lease()
            leases.acquire(self.name, self.owner)
            return [payload(c) for c in self.service.commands(self.identity.box)]


async def agent_websocket(scope, receive, send):
    event = await receive()
    if event["type"] != "websocket.connect":
        return
    headers = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
    try:
        if len(headers) != 1 or scope.get("query_string"):
            raise AuthenticationFailed()
        client = scope.get("client")
        source_ip = client[0] if client else ""

        identity = await db(
            partial(
                authenticate_agent_header,
                headers[0],
                source_ip=source_ip,
            )
        )
    except AuthenticationFailed:
        await send({"type": "websocket.close", "code": 4401})
        return
    except ServiceError as exc:
        if exc.code == "AUTH_RATE_LIMITED":
            await send({
                "type": "websocket.close",
                "code": 4429,
            })
            return
        raise
    
    if scope["path"] != "/ws/v1/agents":
        await send({"type": "websocket.close", "code": 4404})
        return
    await send({"type": "websocket.accept"})
    control = RemoteControl(identity, uuid4())
    opened = False
    pending = None
    disconnect_cause = "UNKNOWN"
    async def emit(kind, data, correlation=None):
        await send({"type": "websocket.send", "text": json.dumps(envelope(kind, data, correlation), default=serial)})
    try:
        event = await asyncio.wait_for(receive(), timeout=10)
        hello = decode(event.get("text"))
        p = hello["payload"]
        if (hello["type"] != "hello" or set(p) != {"agent_version", "capabilities"}
                or not isinstance(p["agent_version"], str) or len(p["agent_version"]) > 64
                or not isinstance(p["capabilities"], list) or len(p["capabilities"]) > 16
                or any(not isinstance(x, str) or len(x) > 64 for x in p["capabilities"])):
            raise ValueError("INVALID_MESSAGE")
        await db(control.open)
        opened = True
        smile_check = SMILE_CHECK_CAPABILITY in p["capabilities"] and bool(await db(sources_for, identity))
        await db(control.register_hello, p["agent_version"], smile_check)
        await db(register_server_reconnect, identity)
        capabilities = ["audio.v1", "audio.v2", "agenda.excel.v1", "agenda.smile-json.v1",
                        "agent.events.v1", "sessions.capture-ended.v1"]
        if smile_check:
            capabilities.append(SMILE_CHECK_CAPABILITY)
        await emit("ready", {"box": identity.box, "server_time": timezone.now().isoformat(),
            "capabilities": capabilities,
            "heartbeat_interval": settings.CAPTURE_HEARTBEAT_SECONDS}, hello["message_id"])
        next_poll = 0
        last_message = time.monotonic()
        pending = asyncio.create_task(receive())
        while True:
            if time.monotonic() - last_message > settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS:
                disconnect_cause = "CONNECTION_TIMEOUT"
                await send({"type": "websocket.close", "code": 4408})
                break
            if time.monotonic() >= next_poll:
                for command in await db(control.poll):
                    await emit("command", command)
                for config in await db(control.poll_configs):
                    await emit("config_sync", config)
                next_poll = time.monotonic() + settings.CAPTURE_COMMAND_INTERVAL_SECONDS
            done, _ = await asyncio.wait([pending], timeout=max(0, next_poll - time.monotonic()))
            if not done:
                continue
            event = pending.result()
            if event["type"] == "websocket.disconnect":
                break
            last_message = time.monotonic()
            pending = asyncio.create_task(receive())
            message = decode(event.get("text"))
            try:
                kind, data = await db(control.dispatch, message)
                await emit(kind, data, message["message_id"])
            except CaptureError as exc:
                await emit("error", {"code": exc.code, "recoverable": False}, message["message_id"])

    except AuthenticationFailed:
        disconnect_cause = "CREDENTIAL_INVALIDATED"
        await send({"type": "websocket.close", "code": 4401})
    except (ValueError, KeyError, TypeError, TimeoutError) as exc:
        code = "PROTOCOL_INCOMPATIBLE" if str(exc) == "PROTOCOL_INCOMPATIBLE" else (
            "CONNECTION_REPLACED" if str(exc) == "CONNECTION_REPLACED" else "INVALID_MESSAGE")
        await emit("error", {"code": code, "recoverable": code == "CONNECTION_REPLACED"})
        await send({"type": "websocket.close", "code": 4406 if code == "PROTOCOL_INCOMPATIBLE" else 4409})
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if opened:
            await db(control.close, disconnect_cause)
