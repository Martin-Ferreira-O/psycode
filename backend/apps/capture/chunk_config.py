"""Configuración congelada de captura y cotas por sesión; sin estado global mutable."""
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
    """La ausencia del campo conserva el contrato v1 ya publicado."""
    return session.capture_chunk_config.get("audio_chunk_overlap", 1)


def byte_limit(session, legacy_limit):
    if session.capture_chunk_negotiated is not True:
        return legacy_limit
    # PCM de la duración solicitada más cabecera WAV acotada. La línea temporal
    # comprueba además la ventana efectiva (incluidas revocaciones y detenciones).
    return duration(session) * 32000 + 65536
