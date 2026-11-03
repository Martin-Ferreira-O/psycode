"""Adaptadores HTTP. No instancian procesos ni cargan archivos de entorno."""
import time
import httpx
from .domain import JevDecision, Transcription, Word
from .providers.http import json_body, request
from .providers.jev_contract import questions, validate_response
from .providers.speechmatics import BatchClient


class SpeechmaticsTranscriptor:
    def __init__(self, settings, journal_dir, client=None, sleep=time.sleep):
        self.batch = BatchClient(settings, journal_dir, client, sleep)

    def transcribe(self, fragment):
        result = self.batch.transcribe(fragment.path, fragment)
        return Transcription(result["text"], tuple(
            Word(w["text"], w["start"], w["end"], w["speaker"])
            for w in result["words"]), result["provider_cleanup"])


class JevAnalizador:
    def __init__(self, settings, client=None, sleep=time.sleep):
        self.settings, self.client, self.sleep = settings, client, sleep

    def evaluate(self, current, history):
        self.settings.validate("jev")
        own = self.client is None
        client = self.client or httpx.Client(
            headers={"Authorization": f"Bearer {self.settings.analysis_key}"},
            timeout=30, trust_env=False, follow_redirects=False)
        try:
            # Solo contenido redactado y etiquetas técnicas locales. Sin metadatos de sesión.
            response = request(client, "POST", self.settings.analysis_endpoint,
                               safe=False, sleep=self.sleep,
                               deadline=time.monotonic() + self.settings.timeout,
                               json={"model": self.settings.analysis_model,
                                     "state": {"current": current, "history": history},
                                     "questions": questions()})
            data = json_body(response)
            values, context, usage = validate_response(data, self.settings.analysis_model,
                                                       self.settings.analysis_provider)
            return JevDecision(data["model"], context["choice"], tuple(values),
                               usage["input_tokens"], usage["output_tokens"])
        finally:
            if own:
                client.close()
