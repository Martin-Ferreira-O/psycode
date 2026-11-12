"""Adaptadores HTTP. No instancian procesos ni cargan archivos de entorno."""
import json
import re
import time
import httpx
from .errors import JevContextLimit, ProviderError, SubmissionUncertain
from .domain import JevDecision, Transcription, Word
from .providers.http import json_body, request
from .providers.jev_contract import localized_evidence, questions, validate_response
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
        state = {"current": current, "history": history}
        if (unit == "fragment"
                and len(json.dumps(state, ensure_ascii=False, separators=(",", ":"))) > self.settings.jev_block_max_chars):
            raise JevContextLimit("JEV_CONTEXT_LIMIT")
        own = self.client is None
        client = self.client or httpx.Client(
            headers={"Authorization": f"Bearer {self.settings.analysis_key}"},
            timeout=30, trust_env=False, follow_redirects=False)
        try:
            # Solo contenido redactado y etiquetas técnicas locales. Sin metadatos de sesión.
            headers = {"X-Request-Id": request_id} if request_id else {}
            deadline = time.monotonic() + self.settings.timeout
            evidence_turns = [turn["id"] for turn in current.get("turns", ()) if "id" in turn]
            unknown_speakers = [speaker for speaker, role in current.get("speaker_roles", {}).items()
                                if role == "unknown"]
            requested = questions(unit, evidence_turns, unknown_speakers)
            payload = {"model": self.settings.analysis_model, "state": state, "questions": requested}

            def send():
                return request(client, "POST", self.settings.analysis_endpoint,
                               safe=False, sleep=self.sleep, accepted_statuses=(400, 413, 422),
                               headers=headers, deadline=deadline, json=payload)

            response = send()
            context_rejected = not response.is_success and self._context_limit(response)
            if unit == "fragment" and self.settings.analysis_provider == "typesafe" and context_rejected:
                # El rechazo de contexto es definitivo. Reintentar el mismo bloque completo una vez.
                headers["TypeSafe-Danger-Zone-Long-Context"] = "true"
                response = send()
            if not response.is_success:
                if response.status_code == 413 or self._context_limit(response):
                    raise JevContextLimit("JEV_CONTEXT_LIMIT")
                raise ProviderError(f"Proveedor respondió HTTP {response.status_code}")
            try:
                data = json_body(response)
                values, context, usage = validate_response(data, self.settings.analysis_model,
                                                           self.settings.analysis_provider, requested)
            except ProviderError:
                raise SubmissionUncertain("Respuesta JEV no recuperable; requiere revisión") from None
            return JevDecision(data["model"], context["choice"], tuple(values),
                               usage["input_tokens"], usage["output_tokens"],
                               localized_evidence(data["answers"], requested, current))
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
            r"too many tokens|\b(?:per_question_context|per_request_context|jev_context_limit)\b",
            message, re.IGNORECASE) for message in messages(data))
