"""Adaptadores HTTP. No instancian procesos ni cargan archivos de entorno."""
import time
import re
import httpx
from .errors import JevContextLimit, ProviderError, SubmissionUncertain
from .domain import JevDecision, Transcription, Word
from .providers.http import json_body, request
from .providers.jev_contract import questions, validate_response
from .providers.speechmatics import BatchClient


class SpeechmaticsTranscriptor:
    def __init__(self, settings, journal_dir, client=None, sleep=time.sleep):
        self.batch = BatchClient(settings, journal_dir, client, sleep)

    def transcribe(self, fragment, *, checkpoint=None, prepare=None):
        if checkpoint is None:
            result = self.batch.transcribe(fragment.path, fragment)
        else:
            result = self.batch.transcribe(fragment.path, fragment, checkpoint=checkpoint, prepare=prepare)
        return Transcription(result["text"], tuple(
            Word(w["text"], w["start"], w["end"], w["speaker"])
            for w in result["words"]), result["provider_cleanup"])


class JevAnalizador:
    def __init__(self, settings, client=None, sleep=time.sleep):
        self.settings, self.client, self.sleep = settings, client, sleep

    def evaluate(self, current, history, *, request_id=None):
        self.settings.validate("jev")
        unit = current.get("analysis_unit", "utterance")
        if unit == "fragment" and len(current["text"]) > self.settings.jev_block_max_chars:
            raise JevContextLimit("JEV_CONTEXT_LIMIT")
        own = self.client is None
        client = self.client or httpx.Client(
            headers={"Authorization": f"Bearer {self.settings.analysis_key}"},
            timeout=30, trust_env=False, follow_redirects=False)
        try:
            # Solo contenido redactado y etiquetas técnicas locales. Sin metadatos de sesión.
            response = request(client, "POST", self.settings.analysis_endpoint,
                               safe=False, sleep=self.sleep,
                               accepted_statuses=(400, 413, 422),
                               headers={"X-Request-Id": request_id} if request_id else None,
                               deadline=time.monotonic() + self.settings.timeout,
                               json={"model": self.settings.analysis_model,
                                     "state": {"current": current, "history": history},
                                     "questions": questions(unit)})
            if not response.is_success:
                if response.status_code == 413 or self._context_limit(response):
                    raise JevContextLimit("JEV_CONTEXT_LIMIT")
                raise ProviderError(f"Proveedor respondió HTTP {response.status_code}")
            try:
                data = json_body(response)
                values, context, usage = validate_response(data, self.settings.analysis_model,
                                                           self.settings.analysis_provider)
            except ProviderError:
                raise SubmissionUncertain("Respuesta JEV no recuperable; requiere revisión") from None
            return JevDecision(data["model"], context["choice"], tuple(values),
                               usage["input_tokens"], usage["output_tokens"])
        finally:
            if own:
                client.close()

    @staticmethod
    def _context_limit(response):
        # Inspección en memoria; nunca propagar cuerpos ni texto libre al journal/log.
        try:
            data = json_body(response)
        except ProviderError:
            return False
        def messages(value):
            if isinstance(value, str):
                yield value.casefold()
            elif isinstance(value, dict):
                for key in ("error", "detail", "code", "type", "message", "msg"):
                    yield from messages(value.get(key))
            elif isinstance(value, list):
                for item in value:
                    yield from messages(item)
        return any(re.search(
            r"context[_ -]?(?:length|window|limit|size).*(?:exceed|long|large|limit)|"
            r"(?:exceed|maximum|max).*(?:context|tokens)|"
            r"too many tokens|context_length_exceeded|JEV_CONTEXT_LIMIT",
            message, re.IGNORECASE) for message in messages(data))
