from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import monotonic, time

import httpx
from django.conf import settings

from backend.apps.capture.filesystem import lock_file


logger = logging.getLogger(__name__)
PRICING_URL = "https://www.speechmatics.com/pricing.md"
FRESH_SECONDS = 24 * 60 * 60
RETRY_SECONDS = 15 * 60
TIMEOUT_SECONDS = 2
MAX_BYTES = 128 * 1024
RATE_SECTION = "## Speech-to-text list rates (USD per hour)"
RATE_HEADER = ["Mode", "Model", "Current list rate", "Original rate before promotion"]
UNPUBLISHED_RATES = {"—", "On request"}


def _columns(line):
    return [column.strip() for column in line.strip("|").split("|")]


def parse_batch_rates(markdown):
    lines = [line.strip() for line in markdown.splitlines()]
    start = lines.index(RATE_SECTION) + 1
    header = next((i for i in range(start, len(lines)) if lines[i].startswith(("|", "#"))), None)
    if header is None or _columns(lines[header]) != RATE_HEADER:
        raise ValueError("La tabla de tarifas de Speechmatics cambió de formato")
    separator = _columns(lines[header + 1]) if header + 1 < len(lines) else []
    if len(separator) != len(RATE_HEADER) or not all(re.fullmatch(r":?-{3,}:?", col) for col in separator):
        raise ValueError("Encabezado inválido en la tabla de Speechmatics")

    models = {}
    for line in lines[header + 2:]:
        if not line.startswith("|"):
            break
        mode, name, rate, _ = _columns(line)
        if mode != "Pre-recorded":
            continue
        model_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if model_id == "oak-1-medical":
            model_id = "oak-1"
        if not model_id or len(name) > 80 or model_id in models:
            raise ValueError("Fila de tarifa Batch inválida o duplicada")
        if rate not in UNPUBLISHED_RATES and not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,4})?", rate):
            raise ValueError("Importe de tarifa Batch inválido")
        models[model_id] = {"id": model_id, "name": name, "usd_per_hour": None if rate in UNPUBLISHED_RATES else float(rate)}
    if not models:
        raise ValueError("Speechmatics no publicó filas de tarifas Batch")
    return list(models.values())


def _fetch_batch_rates():
    deadline = monotonic() + TIMEOUT_SECONDS
    body = bytearray()
    with httpx.stream("GET", PRICING_URL, headers={"Accept": "text/markdown"}, timeout=TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > MAX_BYTES or monotonic() > deadline:
                raise ValueError("La consulta de tarifas excedió el tamaño o el plazo permitido")
            body.extend(chunk)
    return parse_batch_rates(body.decode("utf-8-sig"))


def _read(path):
    try:
        with path.open("rb") as stream:
            snapshot = json.loads(stream.read(MAX_BYTES + 1))
        if (isinstance(snapshot, dict) and type(snapshot.get("attempted_at")) is int
                and type(snapshot.get("fetched_at")) is int and isinstance(snapshot.get("models"), list)
                and 0 <= snapshot["fetched_at"] <= snapshot["attempted_at"]
                and bool(snapshot["models"]) == bool(snapshot["fetched_at"])):
            return snapshot
    except (OSError, ValueError):
        pass
    return {"attempted_at": 0, "fetched_at": 0, "models": []}


def _write(path, snapshot):
    with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(snapshot, stream, ensure_ascii=False)
            stream.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def _status(snapshot, now):
    fetched_at = snapshot["fetched_at"]
    if not fetched_at:
        return "unavailable"
    return "fresh" if now - fetched_at < FRESH_SECONDS else "stale"


def _refresh_due(snapshot, now):
    return now - snapshot["fetched_at"] >= FRESH_SECONDS and now - snapshot["attempted_at"] >= RETRY_SECONDS


def batch_catalog():
    path = Path(settings.SPEECHMATICS_CATALOG_PATH)
    snapshot = _read(path)
    now = int(time())
    if _refresh_due(snapshot, now):
        try:
            with path.with_suffix(".lock").open("a+b") as lock:
                lock_file(lock)
                snapshot = _read(path)
                now = int(time())
                if _refresh_due(snapshot, now):
                    snapshot["attempted_at"] = now
                    try:
                        models = _fetch_batch_rates()
                    except (httpx.HTTPError, ValueError) as error:
                        logger.warning("No se pudo actualizar el catálogo público de Speechmatics (%s)", type(error).__name__)
                    else:
                        snapshot.update(fetched_at=now, models=models)
                    _write(path, snapshot)
        except OSError as error:
            logger.warning("No se pudo guardar la caché de Speechmatics (%s)", type(error).__name__)

    fetched_at = snapshot["fetched_at"]
    return {
        "models": snapshot["models"],
        "status": _status(snapshot, now),
        "fetched_at": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat() if fetched_at else None,
    }
