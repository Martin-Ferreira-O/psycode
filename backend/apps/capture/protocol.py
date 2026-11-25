import json
import math
from datetime import datetime, timezone
from uuid import UUID, uuid4

VERSION = "1.0"
MAX_BYTES = 65536
TYPES = {
    "hello",
    "ready",
    "sync",
    "state",
    "command",
    "command_ack",
    "command_receipt",
    "heartbeat",
    "heartbeat_receipt",
    "interrupted",
    "interruption_receipt",
    "status",
    "error",
    "config_sync",
    "config_received",
    "config_ack",
    "config_receipt",
    "config_local",
}

CONFIG_CAPABILITY = "agent.config.v1"
CONFIG_KEYS = {"heartbeat_interval"}
CONFIG_ERRORS = {"CONFIG_APPLY_FAILED", "CONFIG_VERSION_CONFLICT", "CONFIG_RECOVERY_FAILED",
                 "INVALID_EFFECTIVE_CONFIG", "MISSING_EFFECTIVE_CONFIG"}


def configuration(value, *, effective=False):
    legacy = {"audio_chunk_duration", "audio_chunk_overlap"} if effective else set()
    if not isinstance(value, dict) or value.keys() - CONFIG_KEYS - legacy:
        raise ValueError("INVALID_CONFIGURATION")
    value = {key:item for key,item in value.items() if key in CONFIG_KEYS}
    for key, item in value.items():
        if effective and key == "heartbeat_interval":
            if type(item) not in (int, float) or not math.isfinite(item) or item <= 0:
                raise ValueError("INVALID_CONFIGURATION")
            continue
        if type(item) is not int or not 1 <= item <= 30:
            raise ValueError("INVALID_CONFIGURATION")
    return dict(value)


def instant(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("INVALID_TIMESTAMP")
    return dt


def identifier(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("INVALID_IDENTIFIER")
    return UUID(value)


def envelope(kind, payload, correlation_id=None):
    data = dict(
        protocol_version=VERSION,
        message_id=str(uuid4()),
        type=kind,
        sent_at=datetime.now(timezone.utc).isoformat(),
        payload=payload,
    )
    if correlation_id is not None:
        data["correlation_id"] = str(correlation_id)
    return data


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
        raise ValueError("INVALID_MESSAGE")
    data = json.loads(raw)
    required = {"protocol_version", "message_id", "type", "sent_at", "payload"}
    if (
        not isinstance(data, dict)
        or not required <= data.keys()
        or data.keys() - required - {"correlation_id"}
    ):
        raise ValueError("INVALID_MESSAGE")
    if data["protocol_version"] != VERSION:
        raise ValueError("PROTOCOL_INCOMPATIBLE")
    identifier(data["message_id"])
    instant(data["sent_at"])
    if "correlation_id" in data:
        identifier(data["correlation_id"])
    if data["type"] not in TYPES or not isinstance(data["payload"], dict):
        raise ValueError("INVALID_MESSAGE")
    return data
