"""Speechmatics Batch adaptado; sin ejecutores ni procesos auxiliares."""
import io
import hashlib
import json
import math
from pathlib import Path
import re
import time
import wave
from dataclasses import replace

import httpx

from backend.common.processing_models import SpeechmaticsModel

from .http import ProviderError, SubmissionUncertain, json_body, request
from .settings import Settings

RATE = 16000
PSYCHOLOGY_VOCABULARY = (
    "anhedonia",
    "autolesión",
    "ideación suicida",
    "psicoeducación",
    "rumiación",
)


def save_job(path, record):
    temporary = path.with_suffix(".tmp")
    import os
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        json.dump(record, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def parse_transcript(data, chunk, job_id):
    results = data.get("results")
    if not isinstance(results, list):
        raise ProviderError("Transcripción inválida")
    words, prefix = [], ""
    previous_owned = False
    for item in results:
        if not isinstance(item, dict):
            raise ProviderError("Palabra inválida")
        if item.get("type") not in {"word", "punctuation"}:
            continue
        try:
            alt = item["alternatives"][0]
            content = alt["content"]
            start, end = float(item["start_time"]), float(item["end_time"])
            if not isinstance(content, str) or not math.isfinite(start + end) or not 0 <= start <= end <= (chunk.end - chunk.context_start) / RATE + .1:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("Palabras del proveedor inválidas") from None
        start += chunk.context_start / RATE
        end += chunk.context_start / RATE
        if item["type"] == "punctuation":
            if item.get("attaches_to", "previous") == "next":
                prefix += content
            elif words and previous_owned:
                words[-1]["text"] += content
            continue
        previous_owned = chunk.start / RATE <= (start + end) / 2 < chunk.end / RATE
        if previous_owned:
            label = None if getattr(chunk, "analysis_unit", None) == "fragment" else alt.get("speaker")
            if label is not None and (not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label)):
                raise ProviderError("Hablante inválido")
            # Batch speaker IDs only have meaning inside this job.
            speaker = f"batch-{chunk.id}-{label}" if label and label != "UU" else None
            words.append({"start": round(start, 3), "end": round(end, 3),
                          "text": " " + prefix + content, "speaker": speaker,
                          "confidence": alt.get("confidence")})
        prefix = ""
    return words

def read_pcm(path, chunk):
    expected = (chunk.end - chunk.context_start) * 2

    try:
        with path.open("rb") as source:
            magic = source.read(12)
            source.seek(0)

            if len(magic) == 12 and magic[:4] == b"RIFF" and magic[8:12] == b"WAVE":
                with wave.open(source, "rb") as wav:
                    if (
                        wav.getnchannels() != 1
                        or wav.getsampwidth() != 2
                        or wav.getframerate() != RATE
                        or wav.getcomptype() != "NONE"
                    ):
                        raise ProviderError("Formato WAV incompatible")
                    if chunk.end > wav.getnframes():
                        raise ProviderError("Audio incompleto")
                    wav.setpos(chunk.context_start)
                    pcm = wav.readframes(chunk.end - chunk.context_start)
            else:
                source.seek(chunk.context_start * 2)
                pcm = source.read(expected)
    except (OSError, wave.Error):
        raise ProviderError("Audio inválido") from None

    if len(pcm) != expected:
        raise ProviderError("Audio incompleto")

    return pcm

class BatchClient:
    def __init__(self, settings: Settings, journal_dir: Path, client=None, sleep=time.sleep, *, settings_loader=None):
        self.settings, self.client, self.sleep = settings, client, sleep
        self.journal_dir = journal_dir
        self.settings_loader = settings_loader

    def transcribe(self, path: Path, chunk, *, checkpoint=None, prepare=None) -> dict:
        settings = self.settings_loader() if self.settings_loader else self.settings
        settings.validate("speechmatics")
        if not 0 <= chunk.context_start <= chunk.start < chunk.end:
            raise ProviderError("Intervalo inválido")
        if checkpoint is None:
            self.journal_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        journal = self.journal_dir / f"{chunk.session_id}-{chunk.id}.json"
        record = checkpoint.data.get("speechmatics") if checkpoint is not None else None
        if record is None:
            record = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {
                "session": chunk.session_id, "sequence": chunk.id, "region": settings.region,
                "state": "new", "job_id": None,
            }
        if record["region"] != settings.region:
            raise ProviderError("El trabajo pertenece a otra región")
        if checkpoint is not None:
            def persist():
                checkpoint.data["speechmatics"] = record
                checkpoint.save()
        else:
            def persist():
                save_job(journal, record)

        if checkpoint is None and record["state"] in {"submitting", "uncertain", "deleted", "delete_pending"}:
            raise SubmissionUncertain("Fragmento ya enviado o incierto; no se reenviará automáticamente")
        base = f"https://{settings.region}.asr.api.speechmatics.com/v2"
        started = time.monotonic()
        diarization = "none" if getattr(chunk, "analysis_unit", None) == "fragment" else "speaker"
        deadline = started + settings.timeout
        own_client = self.client is None
        client = self.client or httpx.Client(timeout=30, headers={
            "Authorization": f"Bearer {settings.speechmatics_key}"}, trust_env=False)
        job_id = record["job_id"]
        timings, cleanup = {}, "pending"
        reference = hashlib.sha256(f"{record['session']}:{chunk.id}".encode()).hexdigest()
        prepared = checkpoint is not None and "utterances" in checkpoint.data
        words = []
        can_delete = checkpoint is None or prepared
        submitted_bytes = (chunk.end - chunk.context_start) * 2
        try:
            if checkpoint is not None and record["state"] in {"submitting", "uncertain"}:
                try:
                    jobs = json_body(request(client, "GET", base + "/jobs/",
                                             deadline=deadline, sleep=self.sleep))["jobs"]
                    matches = [
                        job["id"] for job in jobs
                        if (job.get("config") or {}).get("tracking", {}).get("reference") == reference
                        and job.get("status") not in {"deleted", "expired"}
                        and isinstance(job.get("id"), str)
                        and re.fullmatch(r"[A-Za-z0-9_-]+", job["id"])
                    ]
                except (ProviderError, KeyError, TypeError, AttributeError):
                    matches = []
                if len(matches) != 1:
                    record["state"] = "uncertain"
                    persist()
                    raise SubmissionUncertain("No se pudo reconciliar el envío a Speechmatics")
                job_id = matches[0]
                record.update(job_id=job_id, state="submitted")
                persist()
            if checkpoint is not None and record["state"] in {"deleted", "delete_pending"} and not prepared:
                raise SubmissionUncertain("La transcripción anterior requiere revisión")
            if not job_id:
                pcm = read_pcm(path, chunk)
                audio = io.BytesIO()
                with wave.open(audio, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(pcm)
                record.update(state="submitting", model=settings.model)
                persist()
                transcription_config = {
                    "language": settings.transcription_language,
                    "model": settings.model,
                    "diarization": diarization,
                }
                if diarization == "speaker" and settings.model in SpeechmaticsModel.values:
                    transcription_config["speaker_diarization_config"] = {
                        "speaker_sensitivity": 0.5, "prefer_current_speaker": False,
                    }
                if settings.transcription_language == "multi":
                    transcription_config["language_hints"] = ["es"]
                elif settings.model in {SpeechmaticsModel.ENHANCED, SpeechmaticsModel.STANDARD}:
                    transcription_config["additional_vocab"] = [{"content": term} for term in PSYCHOLOGY_VOCABULARY]
                if settings.model == SpeechmaticsModel.ENHANCED:
                    transcription_config["domain"] = "medical"
                try:
                    response = request(client, "POST", base + "/jobs/", safe=False, sleep=self.sleep,
                                       deadline=deadline, data={"config": json.dumps({"type": "transcription",
                                       "tracking": {"reference": reference},
                                       "transcription_config": transcription_config})},
                                       files={"data_file": ("fragment.wav", audio.getvalue(), "audio/wav")})
                    try:
                        job_id = json_body(response).get("id")
                    except ProviderError:
                        raise SubmissionUncertain("Respuesta de creación inválida; envío incierto") from None
                    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
                        job_id = None
                        raise SubmissionUncertain("No se recibió un identificador válido; envío incierto")
                except SubmissionUncertain:
                    record["state"] = "uncertain"
                    persist()
                    raise
                except ProviderError:
                    record["state"] = "new"
                    persist()
                    raise
                record.update(job_id=job_id, state="submitted")
                persist()
            timings["upload_seconds"] = time.monotonic() - started
            if not prepared:
                polling = time.monotonic()
                while True:
                    try:
                        state = json_body(request(client, "GET", f"{base}/jobs/{job_id}",
                                                  params={"wait": 0}, deadline=deadline, sleep=self.sleep))["job"]["status"]
                    except (KeyError, TypeError):
                        raise ProviderError("Estado de trabajo inválido") from None
                    if state == "done":
                        break
                    if state == "rejected":
                        raise ProviderError("Speechmatics rechazó el fragmento")
                    if state not in {"running", "queued"}:
                        raise ProviderError("Estado de trabajo desconocido")
                    if time.monotonic() + settings.poll_interval >= deadline:
                        raise ProviderError("Speechmatics superó el plazo de procesamiento")
                    self.sleep(settings.poll_interval)
                timings["provider_wait_seconds"] = time.monotonic() - polling
                retrieval = time.monotonic()
                data = json_body(request(client, "GET", f"{base}/jobs/{job_id}/transcript",
                                         params={"format": "json-v2", "wait": 0}, deadline=deadline, sleep=self.sleep))
                words = parse_transcript(data, chunk, job_id)
                timings["download_seconds"] = time.monotonic() - retrieval
                if checkpoint is not None:
                    checkpoint.data["utterances"] = prepare(words)
                    checkpoint.save()
                can_delete = True
        finally:
            try:
                if record["state"] == "deleted":
                    cleanup = "deleted"
                elif job_id and can_delete:
                    deleting = time.monotonic()
                    try:
                        request(client, "DELETE", f"{base}/jobs/{job_id}", params={"force": "true"},
                                sleep=self.sleep, deadline=time.monotonic() + 30)
                        record["state"] = cleanup = "deleted"
                    except ProviderError:
                        record["state"] = cleanup = "delete_pending"
                    timings["cleanup_seconds"] = time.monotonic() - deleting
                    persist()
            finally:
                if own_client:
                    client.close()
        seconds = time.monotonic() - started
        if "model" in record:
            settings = replace(settings, model=record["model"])
        return {"id": chunk.id, "start": chunk.start / RATE, "end": chunk.end / RATE,
                "context_start": chunk.context_start / RATE,
                "text": "".join(w["text"] for w in words).strip(), "words": words,
                "inference_seconds": seconds, "rtf": seconds / ((chunk.end - chunk.start) / RATE),
                "provider": "speechmatics", "provider_job_id": job_id,
                "provider_cleanup": cleanup, "timings": timings,
                "submitted_audio_seconds": submitted_bytes / (RATE * 2),
                "configuration": settings.public() | {"diarization": diarization}}

