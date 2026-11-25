import wave
from datetime import timedelta
from .models import AUDIO_TEST_ORIGIN, FragmentJob
from .chunk_config import duration, overlap as configured_overlap
from .storage import FragmentError

KEYS = {"session_start_sample", "session_end_sample", "new_audio_start_sample", "sample_rate", "chunk_samples", "overlap_samples"}
TOLERANCE_SECONDS = 0.1

def validate(temporal, upload, session, number, captured_at, now):
    def reject():
        raise FragmentError("INVALID_AUDIO_TIMELINE", 422)
    t = temporal
    if (not isinstance(t, dict) or set(t) != KEYS
            or any(type(v) is not int or not 0 <= v <= 9223372036854775806 for v in t.values())):
        reject()
    start, end, new = (t[k] for k in ("session_start_sample", "session_end_sample", "new_audio_start_sample"))
    rate, chunk, overlap = t["sample_rate"], t["chunk_samples"], t["overlap_samples"]
    configured = duration(session) if session.capture_chunk_negotiated is True else None
    if configured is not None and (chunk != configured * 16000 or overlap != configured_overlap(session) * 16000):
        reject()
    if rate != 16000 or not 0 <= overlap < chunk <= rate * (configured or 600) or not 0 <= start <= new < end or end - start > chunk:
        reject()
    try:
        upload.seek(0)
        with wave.open(upload, "rb") as wav:
            if wav.getnframes() != end - start:
                reject()
    except (wave.Error, EOFError):
        reject()
    finally:
        upload.seek(0)
    profile = {"sample_rate": rate, "chunk_samples": chunk, "overlap_samples": overlap}
    if session.audio_profile and session.audio_profile != profile:
        reject()
    previous = FragmentJob.objects.filter(sequence__session=session, sequence__number=number-1).select_related("sequence").first()
    if number == 0:
        if start != 0 or new != 0:
            reject()
    else:
        if not previous or not previous.temporal:
            reject()
        p = previous.temporal
        if (new != p["session_end_sample"] or start != new - overlap
                or p["session_end_sample"] - p["session_start_sample"] != chunk):
            reject()
        expected = previous.sequence.captured_at + timedelta(seconds=(start-p["session_start_sample"]) / rate)
        if abs((captured_at - expected).total_seconds()) > 1 / rate + 0.000001:
            reject()
    upper = min(v for v in (session.scheduled_end, session.authorization_ended_at if session.origin != AUDIO_TEST_ORIGIN else None, session.stop_requested_at, session.actual_end, now) if v is not None)
    if captured_at + timedelta(seconds=(end-start)/rate) > upper + timedelta(seconds=TOLERANCE_SECONDS):
        reject()
    if not session.audio_profile:
        session.audio_profile = profile
        session.save(update_fields=["audio_profile"])
