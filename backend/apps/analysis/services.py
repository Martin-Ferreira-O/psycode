"""Reglas y coordinación interna. Sin rutas HTTP, colas auxiliares ni notificaciones."""
from dataclasses import asdict
import json
from pathlib import Path
import re
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

from backend.apps.alerts.exceptions import AlertAlreadyExists
from .domain import AnalysisResult, AnalysisState, Fragment, FragmentRejected, Signal
from .errors import ProviderError, SubmissionUncertain
from .ports import AnalizadorDeSenales, FragmentLedger, TechnicalAudit, Transcriptor
from .privacy import redact
from .rules import align_words, context_flags, jev_candidates

MATRIX = json.loads(Path(__file__).with_name("matrix.json").read_text(encoding="utf-8"))


def redact_for_jev(text, fragment, secrets=(), terms=()):
    # Identificadores/rutas/secretos pueden aparecer también dentro del texto.
    forbidden = (fragment.session_id, str(fragment.path), *secrets, *terms)
    text = redact(text, tuple(t for t in forbidden if t))
    for pattern in (r"https?://\S+", r"[A-Za-z]:[\\/][^\s]+",
                    r"(?<!\w)/(?:[^\s/]+/)*[^\s]+",
                    r"(?i)\b(?:bearer\s+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*)\S+"):
        text = re.sub(pattern, "[DATO_RESERVADO]", text)
    return text


class AnalysisService:
    """Instancia por trabajador, secuencial. Contexto acotado y aislado por UUID."""
    def __init__(self, transcriptor: Transcriptor, analyzer: AnalizadorDeSenales,
                 ledger: FragmentLedger, alerts, audit: TechnicalAudit, *,
                 redact_terms=(), secrets=(), max_sessions=32):
        self.transcriptor, self.analyzer, self.ledger = transcriptor, analyzer, ledger
        self.alerts, self.audit = alerts, audit
        self.redact_terms, self.secrets = redact_terms, secrets
        self.histories = {}
        self.max_sessions = max_sessions
        self._lock = Lock()

    def close_session(self, session_id):
        with self._lock:
            self.histories.pop(session_id, None)

    def process(self, fragment: Fragment, *, roles: dict[str, str] | None = None) -> AnalysisResult:
        # No background process/stdout pipes to deadlock under Windows spawn.
        with self._lock:
            return self._process(fragment, roles or {})

    def _process(self, fragment, roles):
        if fragment.session_id not in self.histories and len(self.histories) >= self.max_sessions:
            raise FragmentRejected("Límite de contextos; cierre sesiones terminadas")
        if fragment.sequence > 0 and fragment.session_id not in self.histories:
            raise FragmentRejected("Contexto de sesión no disponible; requiere revisión tras reinicio")
        self.ledger.claim(fragment)
        history = self.histories.setdefault(fragment.session_id, [])
        decisions, signals, errors = [], [], []
        try:
            transcription = self.transcriptor.transcribe(fragment)
        except (ProviderError, OSError):
            self.audit.failure("SPEECHMATICS_FAILED")
            return AnalysisResult(fragment.session_id, fragment.sequence,
                                  AnalysisState.INDETERMINATE, error_codes=("SPEECHMATICS_FAILED",))
        if transcription.cleanup != "deleted":
            errors.append("SPEECHMATICS_DELETE_PENDING")
            self.audit.failure(errors[-1])
        words = [asdict(w) for w in transcription.words]
        utterances = align_words(words, [{"start": w.start, "end": w.end, "speaker": w.speaker}
                                        for w in transcription.words])
        if not utterances:
            errors.append("TEXT_NOT_EVALUABLE")
        for utterance in utterances:
            text = redact_for_jev(utterance["text"].strip(), fragment, self.secrets, self.redact_terms)
            history[:] = [h for h in history if h["end"] >= utterance["start"] - 60]
            while history and sum(len(h["text"]) for h in history) + len(text) > 12000:
                history.pop(0)
            # Roles solo confirmados por un llamador interno, nunca inferidos de S1/S2.
            role = roles.get(utterance["speaker"], "unknown")
            role = role if role in {"patient", "professional", "unknown"} else "unknown"
            current = {"text": text, "start": utterance["start"], "end": utterance["end"],
                       "role": role}
            try:
                if not text or len(text) > 12000:
                    raise ProviderError("Texto no evaluable")
                decision = self.analyzer.evaluate(current, list(history))
                decisions.append(decision)
                candidates = jev_candidates(text, decision.values, MATRIX,
                                            "\n".join(h["text"] for h in history))
                flags = context_flags(text)
                evaluable = (decision.context == "afirmacion_propia" and role == "patient"
                             and utterance["attribution"] == "assigned"
                             and not set(flags).intersection({"pregunta", "cita", "referencia_a_terceros", "antecedente_temporal"}))
                if not evaluable:
                    errors.append("CONTEXT_NOT_EVALUABLE")
                elif not candidates and any(v >= .55 for v in decision.values[1:]):
                    # Las puertas léxicas pueden abstenerse ante una puntuación alta.
                    errors.append("TEXT_NOT_EVALUABLE")
                else:
                    for candidate in candidates:
                        level = candidate["matrix_level"]
                        # Conversión operativa documentada en MONGODB.md; nunca persistir 0–7.
                        severity = 1 if level <= 2 else 2 if level <= 4 else 3
                        signals.append(Signal(candidate["category_id"], level, severity, text,
                                              utterance["start"], utterance["end"], utterance["speaker"]))
            except ProviderError as exc:
                code = "JEV_SUBMISSION_UNCERTAIN" if isinstance(exc, SubmissionUncertain) else "JEV_FAILED"
                errors.append(code)
                self.audit.failure(code)
            history.append(current)
            while history and sum(len(h["text"]) for h in history) > 12000:
                history.pop(0)
        state = (AnalysisState.INDETERMINATE if errors else
                 AnalysisState.SIGNAL if signals else AnalysisState.NO_SIGNAL)
        result = AnalysisResult(fragment.session_id, fragment.sequence, state, transcription,
                                tuple(signals), tuple(decisions), tuple(sorted(set(errors))))
        self.register_signals(fragment, result)
        return result

    def register_signals(self, fragment: Fragment, result: AnalysisResult) -> None:
        """Se puede reintentar esta entrega interna sin volver a llamar a proveedores."""
        if (result.contract_version != "1.0" or result.session_id != fragment.session_id
                or result.sequence != fragment.sequence):
            raise FragmentRejected("Resultado no corresponde al fragmento")
        if result.state != AnalysisState.SIGNAL or result.error_codes:
            return
        for signal in result.signals:
            ident = str(uuid5(NAMESPACE_URL, f"psycode:1.0:{fragment.session_id}:{fragment.sequence}:"
                             f"{signal.start}:{signal.end}:{signal.category_id}"))
            try:
                self.alerts.register_alert(
                    alerta_id=ident, box=fragment.box, tipo_riesgo="riesgo_suicida",
                    nivel_severidad=signal.severity, fecha_hora=fragment.captured_at,
                    sesion_id=fragment.session_id, origen="analysis.speechmatics-jev/1.0",
                    descripcion=" ".join(signal.excerpt.split())[:500])
            except AlertAlreadyExists:
                pass
