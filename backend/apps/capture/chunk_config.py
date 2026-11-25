from math import ceil

CAPABILITY = "audio.chunk-config.v1"
CAPABILITY_V2 = "audio.chunk-config.v2"


def snapshot():
    from backend.apps.operational.models import OperationalConfiguration
    config = OperationalConfiguration.load()
    return {"audio_chunk_duration": config.audio_chunk_duration,
            "audio_chunk_mode": config.audio_chunk_mode, "analysis_unit": "fragment"}


def duration(session):
    config = session.capture_chunk_config
    if not config:
        return None
    window = max(10, ceil((session.scheduled_end - session.scheduled_start).total_seconds()))
    return window if config["audio_chunk_mode"] == "session" else min(config["audio_chunk_duration"], window)


def overlap(session):
    return session.capture_chunk_config.get("audio_chunk_overlap", 1)


def byte_limit(session, legacy_limit):
    if session.capture_chunk_negotiated is not True:
        return legacy_limit
    return duration(session) * 32000 + 65536
