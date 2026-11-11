"""Puebla una instalación de desarrollo con un historial sintético relacionado."""

import logging
from datetime import timedelta
from hashlib import sha256
from secrets import token_hex
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from backend.apps.accounts.management.commands.seed_demo_user import DEMO_EMAIL, DEMO_PASSWORD, DEMO_USERNAME
from backend.apps.accounts.models import AuthRateLimit, PasswordReset, PasswordResetRateLimit, RefreshSession, Role, User
from backend.apps.agenda.models import AgendaBoxRevision, AgendaCollection, SmileCatalogState, SmileCollectorCheck, SmileRoom
from backend.apps.alerts.demo import DEMO_ALERTS, ORIGEN
from backend.apps.alerts.domain import EstadoEvaluacion
from backend.apps.alerts.exceptions import AlertAlreadyExists, EvaluationAlreadyRegistered
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.capture import models as capture
from backend.apps.operational.models import OperationalConfiguration
from backend.common.errors import PersistenceUnavailable

SOURCE = "smile-demo"
PC_COUNT = 16
USER_COUNT = 24


def demo_id(kind, number):
    return uuid5(NAMESPACE_URL, f"psycode.example.test/seed-demo/{kind}/{number}")


def digest(value):
    return sha256(str(value).encode()).hexdigest()


def seed_users(now):
    password = make_password(DEMO_PASSWORD)
    admin, _ = User.objects.get_or_create(
        username="psycode_demo_admin",
        defaults={
            "id": demo_id("admin", 0), "email": "admin@psycode.example.test",
            "first_name": "Admin", "last_name": "Demo", "role": Role.ADMIN,
            "password": password,
        },
    )
    if admin.pk != demo_id("admin", 0):
        raise CommandError("El nombre psycode_demo_admin ya pertenece a otra cuenta.")
    User.objects.get_or_create(
        username=DEMO_USERNAME,
        defaults={
            "email": DEMO_EMAIL, "first_name": "Equipo", "last_name": "Autonoma",
            "password": password,
        },
    )
    for index in range(1, USER_COUNT + 1):
        user, _ = User.objects.get_or_create(
            pk=demo_id("user", index),
            defaults={
                "username": f"psycode_demo_{index:02}", "email": f"usuario{index:02}@psycode.example.test",
                "first_name": ("Andrea", "Camila", "Diego", "Francisca", "Javier", "Valentina")[index % 6],
                "last_name": f"Demo {index:02}", "role": Role.ADMIN if index % 6 == 0 else Role.SUPERVISOR,
                "is_active": index % 5 != 0, "password": "!",
            },
        )
        key = digest(user.pk)
        expired = now - timedelta(days=index)
        RefreshSession.objects.get_or_create(jti=key, defaults={"user": user, "expires_at": expired, "revoked_at": expired})
        PasswordReset.objects.get_or_create(user=user, defaults={
            "token_hash": key, "credential_hash": key[:32], "expires_at": expired,
        })
        PasswordResetRateLimit.objects.get_or_create(key=key, defaults={"window_started_at": expired, "count": index % 5})
        AuthRateLimit.objects.get_or_create(key=key, defaults={"expires_at": expired, "count": index % 5})
    return admin


def seed_pcs(now, admin):
    SmileCatalogState.objects.get_or_create(source=SOURCE, defaults={"generation": 1, "synced_at": now})
    capture.PCRegistryAllocation.objects.get_or_create(pk=1)
    agents = []
    for index in range(1, PC_COUNT + 1):
        box = f"box-{900 + index}"
        room, _ = SmileRoom.objects.get_or_create(pk=demo_id("room", index), defaults={
            "source": SOURCE, "smile_box_id": str(900 + index), "box": box,
            "name": f"Consultorio demo {index:02}", "available": index % 7 != 0, "last_seen_at": now,
        })
        seen_at = now - timedelta(hours=4 if index % 3 == 0 else 0, seconds=index)
        agent, _ = capture.AgentRegistration.objects.get_or_create(pk=demo_id("pc", index), defaults={
            "name": f"PC Psicología Demo {index:02}", "smile_room": room, "box": box,
            "token_sha256": token_hex(32), "last_seen_at": seen_at,
            "revoked_at": seen_at if index % 7 == 0 else None,
        })
        agents.append(agent)
        capture.AgentStatus.objects.get_or_create(box=box, defaults={"seen_at": seen_at})
        capture.PCPairingCode.objects.get_or_create(agent=agent, defaults={
            "code_hash": digest(demo_id("pairing", index)), "expires_at": now - timedelta(days=2),
        })
        SmileCollectorCheck.objects.get_or_create(agent=agent, defaults={
            "source": SOURCE, "requested_at": seen_at - timedelta(minutes=3),
            "expires_at": seen_at - timedelta(minutes=1), "state": "expired",
        })
        capture.AgentConfiguration.objects.get_or_create(agent=agent, version=1, defaults={
            "requested_by": admin.pk, "state": capture.ConfigurationState.APPLIED,
        })
        capture.RuntimeLease.objects.get_or_create(name=f"seed-demo:{box}", defaults={
            "owner": agent.pk, "expires_at": now - timedelta(days=1),
        })
    return agents


def seed_history(now, agents, admin, count):
    sessions = []
    first_session = capture.CaptureSession.objects.filter(pk=demo_id("session", 0)).first()
    history_end = first_session.scheduled_end if first_session else now - timedelta(minutes=15)
    appointments = {agent.box: [] for agent in agents}
    for index in range(count):
        agent = agents[index % len(agents)]
        end = history_end - timedelta(minutes=97 * index)
        start = end - timedelta(minutes=45)
        failed = index % 5 == 0
        state = capture.SessionState.FAILED if failed else capture.SessionState.COMPLETED
        session, _ = capture.CaptureSession.objects.get_or_create(pk=demo_id("session", index), defaults={
            "box": agent.box, "state": state, "origin": "agenda",
            "scheduled_start": start, "scheduled_end": end, "authorized_at": start, "authorization_ended_at": end,
            "actual_start": start, "actual_end": end, "closed_at": end, "last_seen_at": end,
            "next_sequence": 1, "final_sequence": 0, "error_code": "AGENT_OFFLINE" if failed else "",
        })
        sessions.append(session)
        start, end = session.scheduled_start, session.scheduled_end
        appointments[agent.box].append({
            "inicio": start.isoformat(), "termino": end.isoformat(), "estatus": "REALIZADA",
        })
        command, _ = capture.AgentCommand.objects.get_or_create(session=session, kind=capture.CommandKind.START, defaults={
            "created_at": start, "delivered_at": start, "delivery_count": 1,
            "acknowledged_at": start, "succeeded": True, "occurred_at": start,
        })
        capture.CaptureEvent.objects.get_or_create(pk=demo_id("capture-event", index), defaults={
            "session": session, "timestamp": end, "action": "capture.session.failed" if failed else "capture.session.completed",
            "state": session.state, "command_id": command.pk, "error_code": session.error_code,
        })
        sequence, _ = capture.AcceptedSequence.objects.get_or_create(session=session, number=0, defaults={
            "captured_at": start, "accepted_at": start + timedelta(seconds=30), "agent_id": str(agent.pk),
        })
        storage_key = f"{demo_id('storage', index).hex}.blob"
        size = 960_000 + 32_000 * (index % 12)
        capture.FragmentJob.objects.get_or_create(sequence=sequence, defaults={
            "storage_key": storage_key, "size": size, "checksum": digest(storage_key), "finished_at": end,
            "sensitive_expired_at": end, "attempts": 1, "state": capture.FragmentJob.State.COMPLETED,
            "result": capture.FragmentJob.Result.RISK_DETECTED,
        })
        capture.StorageDeletion.objects.get_or_create(key=storage_key, defaults={
            "state": "deleted", "attempts": 1, "removed_at": end, "size": size,
        })
        capture.StorageCleanupRun.objects.get_or_create(pk=demo_id("cleanup", index), defaults={
            "started_at": end, "finished_at": end + timedelta(seconds=2), "source": "manual", "actor_id": admin.pk,
            "outcome": "success", "freed_bytes": size, "removed": 1, "audit_sent_at": end,
        })
        if failed:
            outage, created = capture.ServerConnectivityOutage.objects.get_or_create(pk=demo_id("outage", index), defaults={
                "agent": agent, "box": agent.box, "started_at": end - timedelta(minutes=2), "recovered_at": end,
                "recovery_detected_at": end, "start_time_quality": capture.ServerConnectivityOutage.TimeQuality.ESTIMATED,
            })
            if created:
                capture.ServerConnectivityOutage.objects.filter(pk=outage.pk).update(detected_at=outage.started_at)
            capture.AgentConnectivityEvent.objects.get_or_create(agent_id=str(agent.pk), event_id=demo_id("connectivity", index), defaults={
                "box": agent.box, "session_id": session.pk, "kind": "wss.reconnected",
                "occurred_at": end, "received_at": end, "outage_id": demo_id("agent-outage", index), "duration_ms": 120_000,
            })
    for index, agent in enumerate(agents):
        test_start = history_end - timedelta(days=8, minutes=10 * index)
        test_end = test_start + timedelta(seconds=10)
        test_session, _ = capture.CaptureSession.objects.get_or_create(pk=demo_id("audio-test", index), defaults={
            "box": agent.box, "state": capture.SessionState.COMPLETED, "origin": capture.AUDIO_TEST_ORIGIN,
            "scheduled_start": test_start, "scheduled_end": test_end, "authorized_at": test_start,
            "authorization_ended_at": test_end, "actual_start": test_start, "actual_end": test_end,
            "closed_at": test_end, "last_seen_at": test_end, "final_sequence": -1,
        })
        capture.AudioTest.objects.get_or_create(session=test_session, defaults={
            "agent": agent, "scenario": "neutral", "samples": 16_000, "expires_at": test_end,
        })
        collection, _ = AgendaCollection.objects.get_or_create(collection_id=demo_id("agenda", index), defaults={
            "source": SOURCE, "agent_id": str(agent.pk), "received_at": now, "outcome": "valid",
            "scope": {"boxes": [agent.box]},
        })
        revision, _ = AgendaBoxRevision.objects.get_or_create(box=agent.box, defaults={
            "collection": collection, "appointments": appointments[agent.box],
        })
        if revision.collection_id == collection.pk:
            existing_starts = {record["inicio"] for record in revision.appointments}
            new_records = [record for record in appointments[agent.box] if record["inicio"] not in existing_starts]
            if new_records:
                revision.appointments = sorted(revision.appointments + new_records, key=lambda record: record["inicio"])
                revision.save(update_fields=["appointments"])
    return sessions


def seed_alerts(repository, sessions, admin):
    service = AlertsService(repository)
    evaluations = (EstadoEvaluacion.CORRECTA, EstadoEvaluacion.FALSO_POSITIVO, EstadoEvaluacion.NEUTRO)
    for index, session in enumerate(sessions):
        spec = DEMO_ALERTS[index % len(DEMO_ALERTS)]
        alert_id = str(demo_id("alert", index))
        try:
            service.register_alert(
                alerta_id=alert_id, box=session.box, tipo_riesgo=spec["tipo_riesgo"],
                nivel_severidad=spec["nivel_severidad"], fecha_hora=session.actual_start,
                sesion_id=str(session.pk), origen=ORIGEN, descripcion="Alerta sintética de demostración.",
            )
        except AlertAlreadyExists:
            repository.ensure_registration_audit(repository.get_alert(alert_id))
        if index % 2 == 0:
            try:
                service.record_evaluation(alert_id, evaluations[(index // 2) % len(evaluations)], str(admin.pk), admin.username)
            except EvaluationAlreadyRegistered:
                pass


class Command(BaseCommand):
    help = "Carga datos sintéticos de demostración en SQL y MongoDB."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=96, help="Cantidad de sesiones y alertas (por defecto: 96).")
        parser.add_argument("--sql-only", action="store_true", help="Carga únicamente las tablas SQL.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("El seed requiere DJANGO_DEBUG=true.")
        count = options["count"]
        if count < 1:
            raise CommandError("--count debe ser mayor que cero.")
        repository = None if options["sql_only"] else AlertsRepository()
        try:
            if repository is not None:
                repository.ensure_schema()
            with transaction.atomic():
                now = timezone.now()
                OperationalConfiguration.load()
                admin = seed_users(now)
                agents = seed_pcs(now, admin)
                sessions = seed_history(now, agents, admin, count)
            if repository is not None:
                audit_logger = logging.getLogger("psycode.audit")
                previous_level = audit_logger.level
                audit_logger.setLevel(logging.WARNING)
                try:
                    seed_alerts(repository, sessions, admin)
                finally:
                    audit_logger.setLevel(previous_level)
        except PersistenceUnavailable as exc:
            raise CommandError("MongoDB no está disponible. Revisa MONGODB_URI y vuelve a ejecutar el seed.") from exc
        self.stdout.write(self.style.SUCCESS(
            f"Demo lista: {USER_COUNT + 2} usuarios, {PC_COUNT} PCs y {count} sesiones clínicas y {PC_COUNT} pruebas de audio. "
            f"{count if repository is not None else 0} alertas solicitadas en esta ejecución. "
            f"Acceso administrador: {admin.username} / {DEMO_PASSWORD}."
        ))
