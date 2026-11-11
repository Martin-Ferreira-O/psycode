"""Reglas y coordinación interna. Sin rutas HTTP, colas auxiliares ni notificaciones."""
from dataclasses import asdict
import json
from pathlib import Path
import re
from threading import Lock
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.apps.alerts.exceptions import AlertAlreadyExists
from backend.common.errors import PersistenceUnavailable
from .domain import AnalysisContextLost, AnalysisResult, AnalysisState, Fragment, FragmentRejected, JevDecision, Signal
from .errors import AnalysisRetry, ProviderError, SubmissionUncertain
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
        self.evidence = {}
        self.max_sessions = max_sessions
        self._lock = Lock()

    def close_session(self, session_id):
        with self._lock:
            self.histories.pop(session_id, None)
            self.evidence.pop(session_id, None)

    def process(self, fragment: Fragment, *, roles: dict[str, str] | None = None) -> AnalysisResult:
        # No background process/stdout pipes to deadlock under Windows spawn.
        with self._lock:
            try:
                return self._process(fragment, roles or {})
            except Exception:
                self.audit.failure("FLOW_INTERRUPTED", sesion_id=fragment.session_id,
                                   sequence=fragment.sequence)
                raise

    def resume(self, fragment, *, roles, checkpoint, previous):
        with self._lock:
            session_id = fragment.session_id
            self.histories[session_id] = checkpoint.data.get("history", previous.get("history", [])).copy()
            self.evidence[session_id] = previous.get("evidence", []).copy()
            try:
                if "result" in checkpoint.data:
                    pending = checkpoint.data["result"]
                    result = AnalysisResult(
                        session_id, fragment.sequence, AnalysisState(pending["state"]),
                        signals=tuple(Signal(**signal) for signal in pending["signals"]),
                        error_codes=tuple(pending["error_codes"]),
                    )
                else:
                    result = self._process(fragment, roles, checkpoint)
                self.register_signals(fragment, result, checkpoint=checkpoint)
                return result, {
                    "history": self.histories[session_id],
                    "evidence": self.evidence[session_id],
                    "speechmatics": checkpoint.data.get("speechmatics", {}),
                    "jev_requests": checkpoint.data.get("jev_requests", []),
                    **({"test_alerts": checkpoint.data.get("test_alerts", [])} if fragment.audio_test else {}),
                }
            finally:
                self.histories.pop(session_id, None)
                self.evidence.pop(session_id, None)

    def _utterances(self, fragment, words):
        origin = fragment.session_origin_sample / 16000
        positioned = [dict(word, start=word["start"] + origin, end=word["end"] + origin) for word in words]
        return align_words(positioned, positioned)

    def _prepare_utterances(self, fragment, words):
        return [
            dict(item, text=redact_for_jev(item["text"].strip(), fragment, self.secrets, self.redact_terms))
            for item in self._utterances(fragment, words)
        ]

    def _process(self, fragment, roles, checkpoint=None):
        if fragment.session_id not in self.histories and len(self.histories) >= self.max_sessions:
            raise FragmentRejected("Límite de contextos; cierre sesiones terminadas")
        if fragment.sequence > 0 and fragment.session_id not in self.histories:
            raise AnalysisContextLost("Contexto de sesión no disponible; requiere revisión tras reinicio")
        self.ledger.claim(fragment)
        history = self.histories.setdefault(fragment.session_id, [])
        decisions, signals, errors = [], [], []
        try:
            if checkpoint is None:
                transcription = self.transcriptor.transcribe(fragment)
            elif ("utterances" not in checkpoint.data
                  or checkpoint.data["speechmatics"]["state"] != "deleted"):
                checkpoint.data.setdefault("roles", roles)
                transcription = self.transcriptor.transcribe(
                    fragment, checkpoint=checkpoint, prepare=lambda words: self._prepare_utterances(fragment, words),
                )
            else:
                transcription = None
        except (ProviderError, OSError) as exc:
            if checkpoint is not None:
                code = ("SPEECHMATICS_UNCERTAIN" if isinstance(exc, SubmissionUncertain)
                        else "SPEECHMATICS_FAILED")
                raise AnalysisRetry(code) from exc
            self.audit.failure("SPEECHMATICS_FAILED", sesion_id=fragment.session_id, sequence=fragment.sequence)
            return AnalysisResult(fragment.session_id, fragment.sequence,
                                  AnalysisState.INDETERMINATE, error_codes=("SPEECHMATICS_FAILED",))
        if transcription is not None and transcription.cleanup != "deleted":
            if checkpoint is not None:
                raise AnalysisRetry("SPEECHMATICS_DELETE_PENDING")
            errors.append("SPEECHMATICS_DELETE_PENDING")
            self.audit.failure(errors[-1], sesion_id=fragment.session_id, sequence=fragment.sequence)
        utterances = (checkpoint.data["utterances"] if checkpoint is not None
                      else self._utterances(fragment, [asdict(word) for word in transcription.words]))
        start = 0
        if checkpoint is not None:
            roles = checkpoint.data["roles"]
            start = checkpoint.data.get("next_utterance", 0)
            errors = checkpoint.data.get("errors", []).copy()
            signals = [Signal(**signal) for signal in checkpoint.data.get("signals", [])]
            if "jev_pending" in checkpoint.data and "jev_response" not in checkpoint.data:
                raise AnalysisRetry("JEV_SUBMISSION_UNCERTAIN")
        if not utterances:
            errors.append("TEXT_NOT_EVALUABLE")
        for index, utterance in enumerate(utterances[start:], start):
            if (fragment.new_audio_start_sample is not None
                    and (utterance["start"] + utterance["end"]) / 2 < fragment.new_audio_start_sample / 16000):
                continue
            text = utterance["text"] if checkpoint is not None else redact_for_jev(
                utterance["text"].strip(), fragment, self.secrets, self.redact_terms)
            history[:] = [h for h in history if h["end"] >= utterance["start"] - 60]
            while history and sum(len(h["text"]) for h in history) + len(text) > 12000:
                history.pop(0)
            # Roles solo confirmados por un llamador interno, nunca inferidos de S1/S2.
            role = "patient" if fragment.audio_test and utterance["attribution"] == "assigned" else roles.get(
                utterance["speaker"], "unknown")
            role = role if role in {"patient", "professional", "unknown"} else "unknown"
            current = {"text": text, "start": utterance["start"], "end": utterance["end"],
                       "role": role}
            try:
                if not text or len(text) > 12000:
                    if checkpoint is not None:
                        errors.append("TEXT_NOT_EVALUABLE")
                        continue
                    raise ProviderError("Texto no evaluable")
                if checkpoint is None:
                    decision = self.analyzer.evaluate(current, list(history))
                elif "jev_response" in checkpoint.data:
                    decision = JevDecision(**checkpoint.data["jev_response"])
                else:
                    request_id = uuid4().hex
                    checkpoint.data["jev_pending"] = {"utterance": index, "request_id": request_id}
                    checkpoint.save()
                    decision = self.analyzer.evaluate(current, list(history), request_id=request_id)
                    checkpoint.data["jev_response"] = asdict(decision)
                    checkpoint.save()
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
                if checkpoint is not None:
                    if not isinstance(exc, SubmissionUncertain):
                        checkpoint.data.pop("jev_pending", None)
                        checkpoint.save()
                    raise AnalysisRetry(code) from exc
                errors.append(code)
                self.audit.failure(code, sesion_id=fragment.session_id, sequence=fragment.sequence)
            history.append(current)
            while history and sum(len(h["text"]) for h in history) > 12000:
                history.pop(0)
            if checkpoint is not None:
                request = checkpoint.data.pop("jev_pending")
                checkpoint.data.setdefault("jev_requests", []).append(request["request_id"])
                checkpoint.data.pop("jev_response", None)
                checkpoint.data.update(next_utterance=index + 1, history=history,
                                       signals=[asdict(signal) for signal in signals], errors=errors)
                checkpoint.save()
        state = (AnalysisState.INDETERMINATE if errors else
                 AnalysisState.SIGNAL if signals else AnalysisState.NO_SIGNAL)
        result = AnalysisResult(fragment.session_id, fragment.sequence, state, transcription,
                                tuple(signals), tuple(decisions), tuple(sorted(set(errors))))
        if checkpoint is None:
            self.register_signals(fragment, result)
        else:
            checkpoint.data["result"] = {
                "state": result.state, "signals": [asdict(signal) for signal in result.signals],
                "error_codes": result.error_codes,
            }
            for key in ("utterances", "roles", "signals", "errors", "next_utterance"):
                checkpoint.data.pop(key, None)
            checkpoint.save()
        return result

    def register_signals(self, fragment: Fragment, result: AnalysisResult, *, checkpoint=None) -> None:
        """Se puede reintentar esta entrega interna sin volver a llamar a proveedores."""
        if (result.contract_version != "1.0" or result.session_id != fragment.session_id
                or result.sequence != fragment.sequence):
            raise FragmentRejected("Resultado no corresponde al fragmento")
        if result.state != AnalysisState.SIGNAL or result.error_codes:
            return
        delivery = checkpoint.data.setdefault("delivery", {}) if checkpoint is not None and not fragment.audio_test else {}
        for signal in result.signals:
            evidence = self.evidence.setdefault(fragment.session_id, [])
            excerpt = " ".join(signal.excerpt.casefold().split())
            if fragment.new_audio_start_sample is not None and any(
                    e[0] == signal.category_id and e[1] == excerpt and max(e[2], signal.start) < min(e[3], signal.end)
                    for e in evidence):
                continue
            ident = str(uuid5(NAMESPACE_URL, f"psycode:1.0:{fragment.session_id}:{fragment.sequence}:"
                             f"{signal.start}:{signal.end}:{signal.category_id}"))
            if fragment.audio_test:
                if checkpoint is not None:
                    checkpoint.data.setdefault("test_alerts", []).append({
                        "id": ident, "category": signal.category_id, "severity": signal.severity,
                        "start": signal.start, "end": signal.end,
                    })
                evidence.append((signal.category_id, excerpt, signal.start, signal.end))
                continue
            def before_notify(alert_id):
                if delivery.get(alert_id) == "sending":
                    if self.alerts.store.has_alert_event(alert_id, "notifications.result"):
                        return False
                    raise AnalysisRetry("NOTIFICATION_UNCERTAIN")
                delivery[alert_id] = "sending"
                checkpoint.save()
                return True

            options = {"before_notify": before_notify} if checkpoint is not None else {}
            try:
                if delivery.get(ident) != "done":
                    self.alerts.register_alert(
                        alerta_id=ident, box=fragment.box, tipo_riesgo="riesgo_suicida",
                        nivel_severidad=signal.severity, fecha_hora=fragment.captured_at,
                        sesion_id=fragment.session_id, origen="analysis.speechmatics-jev/1.0",
                        descripcion=" ".join(signal.excerpt.split())[:500], **options)
                    if checkpoint is not None:
                        delivery[ident] = "done"
                        checkpoint.save()
            except AlertAlreadyExists:
                pass
            except PersistenceUnavailable:
                self.audit.failure("ALERT_PERSISTENCE_FAILED", alerta_id=ident,
                                   sesion_id=fragment.session_id, sequence=fragment.sequence)
                raise
            if fragment.new_audio_start_sample is not None:
                evidence.append((signal.category_id, excerpt, signal.start, signal.end))
                evidence[:] = [e for e in evidence if e[3] >= signal.end - 60][-256:]
