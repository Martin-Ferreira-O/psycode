"""Explicit external-processing configuration, never serialized with secrets."""
from dataclasses import dataclass, field
import json
import os
import re

from backend.common.processing_models import (
    SPEECHMATICS_MODEL_ID_MAX_LENGTH, SPEECHMATICS_MODEL_ID_PATTERN, JevVersion, SpeechmaticsModel,
)

from .http import ProviderError


@dataclass(frozen=True)
class Settings:
    speechmatics_key: str = field(default="", repr=False)
    jev_key: str = field(default="", repr=False)
    openrouter_key: str = field(default="", repr=False)
    jev_provider: str = "auto"
    openrouter_jev_model: str = JevVersion.V114.openrouter_id
    region: str = "eu1"
    model: str = SpeechmaticsModel.ENHANCED
    jev_model: str = JevVersion.V114.typesafe_id
    external_enabled: bool = False
    timeout: float = 300.
    poll_interval: float = 2.
    redact_terms: tuple[str, ...] = field(default=(), repr=False)
    # Cota de la aplicación en caracteres; no equivale a tokens del proveedor.
    jev_block_max_chars: int = 262144

    @classmethod
    def from_env(cls):
        terms = json.loads(os.environ.get("PSYCODE_REDACT_TERMS", "[]"))
        if not isinstance(terms, list):
            raise ProviderError("PSYCODE_REDACT_TERMS debe ser una lista JSON")
        return cls(
            speechmatics_key=os.environ.get("SPEECHMATICS_API_KEY", ""),
            jev_key=os.environ.get("TYPESAFE_API_KEY", ""),
            openrouter_key=os.environ.get("OPENROUTER_API_KEY", ""),
            jev_provider=os.environ.get("JEV_PROVIDER", "auto").lower(),
            region=os.environ.get("SPEECHMATICS_REGION", "eu1").lower(),
            external_enabled=os.environ.get("PSYCODE_EXTERNAL_PROCESSING_ENABLED") == "1",
            timeout=float(os.environ.get("PSYCODE_PROVIDER_TIMEOUT", "300")),
            poll_interval=float(os.environ.get("SPEECHMATICS_POLL_INTERVAL", "2")),
            redact_terms=tuple(terms),
            jev_block_max_chars=int(os.environ.get("JEV_BLOCK_MAX_CHARS", "262144")),
        )

    def validate(self, provider):
        if not self.external_enabled:
            raise ProviderError("Procesamiento externo deshabilitado; configura PSYCODE_EXTERNAL_PROCESSING_ENABLED=1")
        if (self.region not in {"eu1", "us1", "au1"} or not isinstance(self.model, str)
                or len(self.model) > SPEECHMATICS_MODEL_ID_MAX_LENGTH
                or not re.fullmatch(SPEECHMATICS_MODEL_ID_PATTERN, self.model)):
            raise ProviderError("Región o modelo de Speechmatics inválido")
        if not 1 <= self.timeout <= 540 or not .1 <= self.poll_interval <= 30:
            raise ProviderError("Plazos de proveedor inválidos")
        if not all(isinstance(t, str) and t.strip() for t in self.redact_terms):
            raise ProviderError("PSYCODE_REDACT_TERMS debe contener textos no vacíos")
        if provider == "speechmatics":
            if not self.speechmatics_key:
                raise ProviderError("Falta SPEECHMATICS_API_KEY")
        else:
            if type(self.jev_block_max_chars) is not int or self.jev_block_max_chars <= 0:
                raise ProviderError("JEV_BLOCK_MAX_CHARS debe ser un entero positivo")
            if self.jev_provider not in {"auto", "typesafe", "openrouter"}:
                raise ProviderError("JEV_PROVIDER debe ser auto, typesafe u openrouter")
            if not self.analysis_key:
                if self.jev_provider == "auto":
                    raise ProviderError("Configura TYPESAFE_API_KEY u OPENROUTER_API_KEY")
                raise ProviderError("Falta OPENROUTER_API_KEY" if self.analysis_provider == "openrouter" else "Falta TYPESAFE_API_KEY")
            pattern = r"typesafe/jev-\d+\.\d+(?:-\d{8})?" if self.analysis_provider == "openrouter" else r"jev-\d+\.\d+\.\d+"
            if not re.fullmatch(pattern, self.analysis_model):
                raise ProviderError("JEV requiere una versión explícita")

    @property
    def analysis_provider(self):
        if self.jev_provider == "auto":
            return "typesafe" if self.jev_key or not self.openrouter_key else "openrouter"
        return self.jev_provider

    @property
    def analysis_key(self):
        return self.openrouter_key if self.analysis_provider == "openrouter" else self.jev_key

    @property
    def analysis_model(self):
        return self.openrouter_jev_model if self.analysis_provider == "openrouter" else self.jev_model

    @property
    def analysis_endpoint(self):
        return ("https://openrouter.ai/api/alpha/decisions" if self.analysis_provider == "openrouter"
                else "https://api.typesafe.ai/v1/systemone")

    @property
    def transcription_language(self):
        return "multi" if self.model in {SpeechmaticsModel.MELIA, SpeechmaticsModel.OAK} else "es"

    def public(self):
        return {"provider": "speechmatics", "region": self.region, "model": self.model,
                "language": self.transcription_language, "diarization": "speaker", "sample_rate": 16000,
                "jev_model": self.analysis_model, "jev_provider": self.analysis_provider,
                "external_processing": True,
                "timeout_seconds": self.timeout}
