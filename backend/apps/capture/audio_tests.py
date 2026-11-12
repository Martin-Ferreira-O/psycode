"""Recepción de clips ficticios, autenticada por PC y separada de captura."""

from datetime import timedelta
from math import ceil

from django.db import transaction
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from backend.common.responses import success_response
from .authentication import BoxAgentAuthentication
from .chunk_config import snapshot
from .models import AUDIO_TEST_ORIGIN, AcceptedSequence, AgentRegistration, AudioTest, CaptureSession, FragmentJob, SessionState
from .storage import FragmentError

RATE = 16000
OVERLAP = RATE
SCENARIOS = {"neutral", "alerta"}
MAX_SAMPLES = RATE * 600
STOPPED = "AUDIO_TEST_STOPPED"


def load_test(test_id, agent, *, lock=False):
    runs = AudioTest.objects.select_related("session").filter(agent_id=agent.registry_id, session__box=agent.box)
    if lock:
        runs = runs.select_for_update()
    run = runs.filter(pk=test_id).first()
    if run is None:
        raise FragmentError("AUDIO_TEST_NOT_FOUND", 404)
    return run


def accept_test_sequence(run, number, captured_at, now, temporal):
    session = run.session
    if now >= run.expires_at:
        raise FragmentError("AUDIO_TEST_EXPIRED", 409)
    if number != session.next_sequence or number > session.final_sequence:
        raise FragmentError("SEQUENCE_OUT_OF_ORDER", 409)
    chunk = session.audio_profile["chunk_samples"]
    overlap = session.audio_profile["overlap_samples"]
    start = number * (chunk - overlap)
    end = min(start + chunk, run.samples)
    if (temporal is None or temporal["session_start_sample"] != start
            or temporal["session_end_sample"] != end
            or captured_at != session.actual_start + timedelta(seconds=start / RATE)):
        raise FragmentError("INVALID_AUDIO_TIMELINE", 422)
    AcceptedSequence.objects.create(session=session, number=number, captured_at=captured_at, accepted_at=now)
    session.next_sequence += 1
    session.save(update_fields=["next_sequence"])


def status_data(run, now):
    session = run.session
    expected = session.final_sequence + 1
    jobs = list(FragmentJob.objects.filter(sequence__session=session).order_by("sequence__number")
                .values("state", "result", "checkpoint"))
    completed = [job for job in jobs if job["state"] == FragmentJob.State.COMPLETED]
    alerts = [alert for job in completed for alert in job["checkpoint"].get("test_alerts", [])]
    if session.capture_end_reason == STOPPED:
        state = "stopped"
    elif any(job["state"] in {FragmentJob.State.FAILED, FragmentJob.State.REVIEW} for job in jobs):
        state = "failed"
    elif len(completed) == expected:
        state = "completed"
    elif len(jobs) == expected:
        state = "analyzing"
    elif now >= run.expires_at:
        state = "expired"
    else:
        state = "receiving"
    profile = ({"fragment_profile_version": 1,
                "audio_chunk_duration": session.audio_profile["chunk_samples"] // RATE}
               if session.capture_chunk_config else {})
    return {
        **profile,
        "test_id": str(run.pk), "box": session.box, "scenario": run.scenario, "samples": run.samples,
        "started_at": session.actual_start.isoformat(), "state": state,
        "expected": expected, "accepted": len(jobs), "analyzed": len(completed),
        "indeterminate": sum(job["result"] == FragmentJob.Result.INDETERMINATE for job in completed),
        "alerts": alerts,
    }


class AudioTestView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request, test_id):
        return success_response(status_data(load_test(test_id, request.user), timezone.now()), "Estado de prueba")

    @transaction.atomic
    def delete(self, request, test_id):
        run = load_test(test_id, request.user, lock=True)
        now = timezone.now()
        state = status_data(run, now)
        if state["state"] in {"receiving", "analyzing"}:
            run.expires_at = now
            run.save(update_fields=["expires_at"])
            run.session.capture_end_reason = STOPPED
            run.session.save(update_fields=["capture_end_reason"])
            state["state"] = "stopped"
        return success_response(state, "Recepción de prueba cerrada")

    @transaction.atomic
    def put(self, request, test_id):
        versions = request.query_params.getlist("fragment_profile_version")
        if versions and versions != ["1"]:
            raise FragmentError("VALIDATION_ERROR", 400)
        negotiated = bool(versions)
        data = request.data
        if not isinstance(data, dict) or set(data) != {"scenario", "samples"}:
            raise FragmentError("VALIDATION_ERROR", 400)
        scenario, samples = data["scenario"], data["samples"]
        if (not isinstance(scenario, str) or scenario not in SCENARIOS
                or type(samples) is not int or not 0 < samples <= MAX_SAMPLES):
            raise FragmentError("VALIDATION_ERROR", 400)
        agent = AgentRegistration.objects.select_for_update().get(pk=request.user.registry_id)
        now = timezone.now()
        run = AudioTest.objects.select_related("session").filter(pk=test_id, agent=agent, session__box=request.user.box).first()
        if run is not None:
            if ((run.scenario, run.samples) != (scenario, samples)
                    or bool(run.session.capture_chunk_config) != negotiated):
                raise FragmentError("AUDIO_TEST_CONFLICT", 409)
            return success_response(status_data(run, now), "Prueba autorizada")
        if CaptureSession.objects.filter(pk=test_id).exists():
            raise FragmentError("AUDIO_TEST_CONFLICT", 409)
        # Cerrar la recepción habilita otro tramo mientras se analiza lo aceptado.
        for previous in AudioTest.objects.filter(agent=agent, expires_at__gt=now).select_related("session"):
            if status_data(previous, now)["state"] in {"receiving", "analyzing"}:
                raise FragmentError("AUDIO_TEST_ALREADY_RUNNING", 409)
        config = snapshot() if negotiated else {}
        window = max(10, ceil(samples / RATE))
        seconds = (window if config.get("audio_chunk_mode") == "session"
                   else min(config["audio_chunk_duration"], window)) if config else 10
        chunk = seconds * RATE
        end = now + timedelta(seconds=samples / RATE)
        session = CaptureSession.objects.create(
            pk=test_id, box=request.user.box, origin=AUDIO_TEST_ORIGIN, state=SessionState.COMPLETED,
            scheduled_start=now, scheduled_end=end, authorized_at=now, authorization_ended_at=now,
            actual_start=now, actual_end=end, last_seen_at=now, closed_at=end,
            final_sequence=max(0, (samples - OVERLAP - 1) // (chunk - OVERLAP)),
            capture_chunk_config=config,
            audio_profile={"sample_rate": RATE, "chunk_samples": chunk, "overlap_samples": OVERLAP},
        )
        run = AudioTest.objects.create(session=session, agent=agent, scenario=scenario, samples=samples,
                                       expires_at=max(now + timedelta(minutes=5), end + timedelta(minutes=2)))
        return success_response(status_data(run, now), "Prueba autorizada", status=201)
