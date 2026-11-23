"""Adaptadores HTTP. No instancian procesos ni cargan archivos de entorno."""
import json
import re
import time
import httpx
from .errors import JevContextLimit, ProviderError, SubmissionUncertain
from .domain import JevDecision, Transcription, Word
from .providers.http import json_body, request
from .plain_text import PLAIN_TEXT_VERSION
from .providers.jev_contract import (
    TEXT_CATEGORY_DEFINITIONS, localized_evidence, questions, text_questions, validate_response, validate_text_response,
)
from .providers.speechmatics import BatchClient


class SpeechmaticsTranscriptor:
    def __init__(self, settings, journal_dir, client=None, sleep=time.sleep, *, settings_loader=None):
        self.batch = BatchClient(settings, journal_dir, client, sleep, settings_loader=settings_loader)

    def transcribe(self, fragment, *, checkpoint=None, prepare=None):
        if checkpoint is None:
            result = self.batch.transcribe(fragment.path, fragment)
        else:
            result = self.batch.transcribe(fragment.path, fragment, checkpoint=checkpoint, prepare=prepare)
        return Transcription(result["text"], tuple(
            Word(w["text"], w["start"], w["end"], w["speaker"])
            for w in result["words"]), result["provider_cleanup"])


class JevAnalizador:
    def __init__(self, settings, client=None, sleep=time.sleep, *, settings_loader=None):
        self.settings, self.client, self.sleep = settings, client, sleep
        self.settings_loader = settings_loader

    def evaluate(self, current, history, *, request_id=None):
        settings = self.settings_loader() if self.settings_loader else self.settings
        settings.validate("jev")
        unit = current.get("analysis_unit", "utterance")
        plain = current.get("evidence_scope") == PLAIN_TEXT_VERSION
        state = {"current": current, "history": history}
        if plain:
            state["categories"] = TEXT_CATEGORY_DEFINITIONS
        if (unit == "fragment"
                and len(json.dumps(state, ensure_ascii=False, separators=(",", ":"))) > settings.jev_block_max_chars):
            raise JevContextLimit("JEV_CONTEXT_LIMIT")
        own = self.client is None
        client = self.client or httpx.Client(
            headers={"Authorization": f"Bearer {settings.analysis_key}"},
            timeout=30, trust_env=False, follow_redirects=False)
        try:
            # Solo contenido redactado y etiquetas técnicas locales. Sin metadatos de sesión.
            headers = {"X-Request-Id": request_id} if request_id else {}
            deadline = time.monotonic() + settings.timeout
            evidence_turns = [turn["id"] for turn in current.get("turns", ()) if "id" in turn]
            unknown_speakers = [speaker for speaker, role in current.get("speaker_roles", {}).items()
                                if role == "unknown"]
            review_turns = {}
            for turn in current.get("turns", ()):
                for level in turn.get("review_levels", ()):
                    review_turns.setdefault(level, []).append(turn["review_id"])
            evidence_texts = None
            if current.get("evidence_scope") == "current_turn":
                evidence_texts = {turn["id"]: turn["text"] for turn in current["turns"] if "id" in turn}
            requested = (text_questions(len(current["text"].splitlines())) if plain else
                         questions(unit, evidence_turns, unknown_speakers, review_turns, evidence_texts=evidence_texts))
            payload = {"model": settings.analysis_model, "state": state, "questions": requested}

            def send():
                return request(client, "POST", settings.analysis_endpoint,
                               safe=False, sleep=self.sleep, accepted_statuses=(400, 413, 422),
                               headers=headers, deadline=deadline, json=payload)

            response = send()
            context_rejected = not response.is_success and self._context_limit(response)
            if unit == "fragment" and settings.analysis_provider == "typesafe" and context_rejected:
                # El rechazo de contexto es definitivo. Reintentar el mismo bloque completo una vez.
                headers["TypeSafe-Danger-Zone-Long-Context"] = "true"
                response = send()
            if not response.is_success:
                if response.status_code == 413 or self._context_limit(response):
                    raise JevContextLimit("JEV_CONTEXT_LIMIT")
                raise ProviderError(f"Proveedor respondió HTTP {response.status_code}")
            try:
                data = json_body(response)
                if plain:
                    values, localized, evidence, usage = validate_text_response(
                        data, settings.analysis_model, settings.analysis_provider, requested)
                    return JevDecision(data["model"], "afirmacion_propia" if localized else "incierto", values,
                                       usage["input_tokens"], usage["output_tokens"],
                                       evidence_turns=localized, text_evidence=evidence)
                values, context, usage = validate_response(data, settings.analysis_model,
                                                           settings.analysis_provider, requested)
            except ProviderError:
                raise SubmissionUncertain("Respuesta JEV no recuperable; requiere revisión") from None
            evidence_turns, review_verdicts = localized_evidence(data["answers"], requested, current)
            return JevDecision(data["model"], context["choice"], tuple(values),
                               usage["input_tokens"], usage["output_tokens"],
                               evidence_turns, review_verdicts)
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
