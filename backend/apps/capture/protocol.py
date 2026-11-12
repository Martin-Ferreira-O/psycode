"""Control v1: límites y representación explícita sin dependencias de dominio."""
import json
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
}


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