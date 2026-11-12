"""Congela los turnos de Speechmatics para comparar sobre WAV autorizados."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4
import wave

from dotenv import dotenv_values

from backend.apps.analysis.clients import SpeechmaticsTranscriptor
from backend.apps.analysis.domain import Fragment
from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.services import AnalysisService

RATE = 16000


def transcribe(entry, audio_dir, settings):
    path = audio_dir / entry["wav"]
    digest = sha256(path.read_bytes()).hexdigest()
    if entry.get("sha256", digest) != digest:
        raise ValueError(f"SHA-256 diferente para {entry['id']}")
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
    offset = round(entry["offset"] * RATE)
    fragment = Fragment(str(uuid4()), 0, "diagnostico", datetime.now(timezone.utc), path, end=frames,
                        audio_test=True, analysis_unit="fragment", session_origin_sample=offset,
                        new_audio_start_sample=offset)
    started = monotonic()
    with TemporaryDirectory() as tmp:
        adapter = SpeechmaticsTranscriptor(settings, Path(tmp))
        service = AnalysisService(adapter, Mock(), Mock(), Mock(), Mock(),
                                  redact_terms=settings.redact_terms, secrets=(settings.speechmatics_key,))
        transcript = adapter.transcribe(fragment)
        if transcript.cleanup != "deleted":
            raise RuntimeError(f"Limpieza de Speechmatics pendiente para {entry['id']}")
        turns = service._prepare_block(fragment, [asdict(word) for word in transcript.words])
    print(f"{entry['id']}: {len(turns)} turnos, {monotonic() - started:.2f} s", flush=True)
    roles = entry.get("actual_roles", [])
    gold = entry.get("gold", {})
    if roles and len(roles) != len(turns):
        raise ValueError(f"Cambió la segmentación de {entry['id']}; revisar las etiquetas")
    if any(not 0 <= index < len(turns) for indices in gold.values() for index in indices):
        raise ValueError(f"Turno de evidencia inexistente en {entry['id']}")
    return {
        "id": entry["id"], "source": "diagnostic", "diagnostic": True, "offset": entry["offset"], "frames": frames,
        "new_audio_start_sample": offset, "wav_sha256": digest, "utterances": turns,
        "roles": {}, "actual_roles": roles or ["unknown"] * len(turns), "gold": gold,
        "cleanup": transcript.cleanup,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    env = {**dotenv_values(".env"), **os.environ}
    settings = replace(Settings(), external_enabled=True, timeout=150, poll_interval=1,
                       speechmatics_key=env.get("SPEECHMATICS_API_KEY") or "",
                       region=env.get("SPEECHMATICS_REGION") or "eu1",
                       model=env.get("SPEECHMATICS_MODEL") or "enhanced",
                       redact_terms=tuple(json.loads(env.get("PSYCODE_REDACT_TERMS") or "[]")))
    settings.validate("speechmatics")
    args.output.touch(mode=0o600, exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = {row["id"]: row for row in pool.map(lambda entry: transcribe(entry, args.audio_dir, settings), manifest)}
    cases = []
    for entry in manifest:
        if entry.get("context_only"):
            continue
        row = rows[entry["id"]]
        previous = rows[entry["previous"]] if "previous" in entry else None
        if previous is not None and round((row["offset"] - previous["offset"]) * RATE) != previous["frames"]:
            raise ValueError(f"El bloque previo de {entry['id']} debe terminar justo en el límite")
        cases.append(dict(row, previous_utterances=previous["utterances"] if previous else []))
    args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
