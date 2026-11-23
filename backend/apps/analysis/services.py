"""Reglas y coordinación interna. Sin rutas HTTP, colas auxiliares ni notificaciones."""
from dataclasses import asdict
import re
from threading import Lock
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.apps.alerts.domain import DESCRIPCION_MAX, ORIGEN_HABLANTE_NO_CONFIRMADO, ORIGEN_PRUEBA_AUDIO
from backend.apps.alerts.exceptions import AlertAlreadyExists
from backend.common.errors import PersistenceUnavailable
from backend.common.processing_models import JEV_DEFAULT_THRESHOLD
from .domain import (
    AnalysisContextLost, AnalysisResult, AnalysisState, EVIDENCE_ABSTENTION_CODES, EvidenceIssue,
    Fragment, FragmentRejected, JevDecision, Signal,
)
from .errors import AnalysisRetry, JevContextLimit, ProviderError, SubmissionUncertain
from .plain_text import PLAIN_TEXT_VERSION, join_previous, plain_signals, text_segments
from .ports import AnalizadorDeSenales, FragmentLedger, TechnicalAudit, Transcriptor
from .privacy import redact
from .rules import (
    align_words, block_claims, context_flags, expressed_time, jev_candidates, literal_candidates,
    requests_non_literal_speech, unattributed_levels, review_priority, MATRIX,
)
from .providers.jev_contract import (
    BLOCK_QUESTIONS_VERSION, CLINICAL_REVIEW_QUESTIONS_VERSIONS, QUESTIONS_VERSION,
)

BLOCK_SENTENCE_END = re.compile(r"[.!?…][\s\"»”]*$")
BLOCK_TURN_GAP = 1.2


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
                 redact_terms=(), secrets=(), max_sessions=32, threshold_loader=None):
        self.transcriptor, self.analyzer, self.ledger = transcriptor, analyzer, ledger
        self.alerts, self.audit = alerts, audit
        self.redact_terms, self.secrets = redact_terms, secrets
        self.histories = {}
        self.evidence = {}
        self.max_sessions = max_sessions
        self.threshold_loader = threshold_loader
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
            previous = previous or {}
            if fragment.analysis_unit == "fragment":
                self.histories[session_id] = []
                self.evidence[session_id] = []
            else:
                self.histories[session_id] = checkpoint.data.get("history", previous.get("history", [])).copy()
                self.evidence[session_id] = previous.get("evidence", []).copy()
            try:
                if "result" in checkpoint.data:
                    pending = checkpoint.data["result"]
                    result = AnalysisResult(
                        session_id, fragment.sequence, AnalysisState(pending["state"]),
                        signals=tuple(Signal(**signal) for signal in pending["signals"]),
                        decisions=tuple(JevDecision(**decision) for decision in pending.get("decisions", [])),
                        error_codes=tuple(pending["error_codes"]),
                        questions_version=pending.get("questions_version", "habla-signals-1"),
                        review_issues=tuple(EvidenceIssue(**issue) for issue in pending.get("review_issues", ())),
                    )
                else:
                    result = self._process(fragment, roles, checkpoint, previous.get("text_tail", ()))
                self.register_signals(fragment, result, checkpoint=checkpoint)
                return result, {
                    "history": self.histories[session_id],
                    "evidence": self.evidence[session_id],
                    "jev_threshold": checkpoint.data.get("jev_threshold", JEV_DEFAULT_THRESHOLD),
                    "speechmatics": checkpoint.data.get("speechmatics", {}),
                    "jev_requests": checkpoint.data.get("jev_requests", []),
                    **({"text_tail": checkpoint.data["text_tail"]} if checkpoint.data.get("text_tail") else {}),
                    **({"analysis_review": [asdict(issue) for issue in result.review_issues]} if result.review_issues else {}),
                    **({"analysis_unit": "fragment", "block_result": {
                        "state": result.state,
                        "decisions": [asdict(decision) for decision in result.decisions],
                        "error_codes": result.error_codes,
                        "questions_version": result.questions_version,
                    }} if fragment.analysis_unit == "fragment" else {}),
                    **({"test_alerts": checkpoint.data.get("test_alerts", [])} if fragment.audio_test else {}),
                    **({"test_error_codes": result.error_codes} if fragment.audio_test and result.error_codes else {}),
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

    def _prepare_block(self, fragment, words):
        # Orden estable y recorrido lineal tras ordenar. El bloque de una hora
        # no necesita comparar cada palabra con todas las demás ni ventanas de 15 s.
        words = sorted(words, key=lambda word: (word["start"], word["end"]))
        items = []
        previous_end = -1
        origin = fragment.session_origin_sample / 16000
        for index, word in enumerate(words):
            overlap = (previous_end > word["start"] or
                       (index + 1 < len(words) and words[index + 1]["start"] < word["end"]))
            previous_end = max(previous_end, word["end"])
            attribution = "overlap" if overlap else "assigned" if word["speaker"] else "unknown"
            start, end = word["start"] + origin, word["end"] + origin
            if (items and items[-1]["speaker"] == word["speaker"]
                    and items[-1]["attribution"] == attribution
                    and not BLOCK_SENTENCE_END.search(items[-1]["text"])
                    and start - items[-1]["end"] < BLOCK_TURN_GAP):
                items[-1]["text"] += word["text"]
                items[-1]["end"] = max(items[-1]["end"], end)
            else:
                items.append({"start": start, "end": end, "speaker": word["speaker"],
                              "attribution": attribution, "text": word["text"]})
        for item in items:
            item["text"] = redact_for_jev(item["text"].strip(), fragment, self.secrets, self.redact_terms)
        return items

    @staticmethod
    def _confirmed_role(speaker, roles):
        role = roles.get(speaker, "unknown") if speaker is not None else "unknown"
        return role if role in {"patient", "professional", "unknown"} else "unknown"

    def _block_current(self, fragment, utterances, roles, model_roles, review_turns=None, *, localize=False):
        turns, aliases, speaker_roles = [], {}, {}
        review_turns = review_turns or {}
        for index, item in enumerate(utterances):
            speaker = item["speaker"]
            turn_id = f"t{index}"
            turn = {"text": item["text"]}
            if item["attribution"] == "assigned" and speaker is not None:
                alias = aliases.setdefault(speaker, f"voz{len(aliases) + 1}")
                speaker_roles[alias] = self._confirmed_role(speaker, model_roles)
                turn["speaker"] = alias
                if self._eligible_block_turn(fragment, item, roles, localize=localize):
                    turn["id"] = turn_id
            else:
                turn["attribution"] = item["attribution"]
            if turn_id in review_turns:
                turn.update(review_id=turn_id, review_levels=review_turns[turn_id])
            turns.append(turn)
        current = {"analysis_unit": "fragment", "speaker_roles": speaker_roles, "turns": turns}
        if localize:
            current["evidence_scope"] = "current_turn"
        return current

    @staticmethod
    def _owns_block_turn(fragment, item):
        return (fragment.new_audio_start_sample is None
                or (item["start"] + item["end"]) / 2 >= fragment.new_audio_start_sample / 16000)

    def _eligible_block_turn(self, fragment, item, roles, *, localize=False):
        if (self._confirmed_role(item["speaker"], roles) != "patient"
                or item["attribution"] != "assigned" or not self._owns_block_turn(fragment, item)):
            return False
        text = item["text"]
        if localize:
            return bool(block_claims(text))
        return bool(text and not set(context_flags(text)).intersection({
            "pregunta", "cita", "referencia_a_terceros", "antecedente_temporal",
        }))

    def _block_review_turns(self, fragment, utterances, roles):
        turns = {}
        for index, item in enumerate(utterances):
            if (self._confirmed_role(item["speaker"], roles) != "unknown"
                    or item["attribution"] not in {"assigned", "unknown"}
                    or not self._owns_block_turn(fragment, item)):
                continue
            levels = unattributed_levels(item["text"])
            if not levels:
                continue
            # Una voz que cambia a mitad de la frase puede separar una negación
            # de lo que sigue. Las fronteras dudosas se conservan como contexto.
            if index:
                previous = utterances[index - 1]
                if requests_non_literal_speech(previous["text"]):
                    continue
                if (item["start"] - previous["end"] < BLOCK_TURN_GAP
                        and (previous["attribution"] == "overlap" or not BLOCK_SENTENCE_END.search(previous["text"]))):
                    continue
            if index + 1 < len(utterances):
                following = utterances[index + 1]
                if (following["start"] - item["end"] < BLOCK_TURN_GAP
                        and (following["attribution"] == "overlap" or not BLOCK_SENTENCE_END.search(item["text"]))):
                    continue
            turns[f"t{index}"] = levels
        return turns

    def _block_signals(self, fragment, utterances, roles, model_roles, decision, threshold,
                       review_turns=None, *, localize=False):
        review_turns = review_turns or {}
        distinct = {}
        evidence_errors = set()
        eligible = False
        below_threshold = False
        for index, item in enumerate(utterances):
            turn_id = f"t{index}"
            review_levels = review_turns.get(turn_id)
            if not review_levels and not self._eligible_block_turn(fragment, item, roles, localize=localize):
                continue
            eligible = True
            if decision.context != "afirmacion_propia":
                continue
            text = item["text"]
            direct_levels = review_levels or unattributed_levels(text)
            if any(decision.values[level] < threshold for level in direct_levels):
                below_threshold = True
            verified = []
            if review_levels:
                for level in review_levels:
                    if decision.values[level] < threshold:
                        continue
                    if turn_id in decision.evidence_turns.get(str(level), ()):
                        severity = review_priority(level)
                        verified.append(Signal(MATRIX["categories"][level]["id"], level, severity, text,
                                               item["start"], item["end"], None, decision.values[level], threshold))
                    else:
                        verdict = decision.review_verdicts.get(str(level), {}).get(turn_id)
                        if verdict in EVIDENCE_ABSTENTION_CODES:
                            evidence_errors.add(EVIDENCE_ABSTENTION_CODES[verdict])
            elif localize:
                for claim in block_claims(text):
                    for candidate in jev_candidates(claim, decision.values, MATRIX, threshold=threshold):
                        level = candidate["matrix_level"]
                        if turn_id not in decision.evidence_turns.get(str(level), ()):
                            continue
                        if level in (1, 2) and direct_levels and level not in direct_levels:
                            continue
                        verified.append(Signal(candidate["category_id"], level, review_priority(level), text,
                                               item["start"], item["end"], item["speaker"],
                                               decision.values[level], threshold))
            else:
                literal = set(literal_candidates(text)) | set(direct_levels)
                for candidate in jev_candidates(text, decision.values, MATRIX, threshold=threshold):
                    level = candidate["matrix_level"]
                    turn_ids = decision.evidence_turns.get(str(level))
                    localized = turn_ids is not None and turn_id in turn_ids
                    literal_verified = level in literal and (
                        turn_ids is None or self._confirmed_role(item["speaker"], model_roles) == "patient")
                    if ((review_turns and not localized)
                            or (level < 3 and not (literal_verified or localized))):
                        continue
                    severity = review_priority(level)
                    verified.append(Signal(candidate["category_id"], level, severity, text,
                                           item["start"], item["end"], item["speaker"], decision.values[level], threshold))
            if verified:
                # A falta de voz identificable, conservar los intervalos por separado.
                voice = item["speaker"] if item["speaker"] is not None else item["start"]
                key = (voice, " ".join(text.casefold().split()))
                best = max(verified, key=lambda signal: signal.matrix_level)
                if key not in distinct or best.matrix_level > distinct[key].matrix_level:
                    distinct[key] = best
        errors = []
        if not eligible or decision.context != "afirmacion_propia":
            errors.append("CONTEXT_NOT_EVALUABLE")
        elif not distinct and (evidence_errors or below_threshold):
            errors.extend(sorted(evidence_errors))
            if below_threshold:
                errors.append("JEV_BELOW_THRESHOLD")
        elif not distinct and (any(v >= threshold for v in decision.values[1:])
                              or any(self._confirmed_role(item["speaker"], roles) == "unknown"
                                     or item["attribution"] != "assigned" for item in utterances)):
            errors.append("TEXT_NOT_EVALUABLE")
        return tuple(distinct.values()), errors

    def _process_block(self, fragment, utterances, roles, transcription, errors, checkpoint, threshold,
                       questions_version, previous_text):
        plain = questions_version == PLAIN_TEXT_VERSION
        model_roles = roles
        if fragment.audio_test and not plain:
            # Convención ficticia exclusiva del diagnóstico sintético autorizado.
            # Las sesiones clínicas y voces sin atribución conservan unknown.
            roles = dict(roles)
            speakers = {item["speaker"] for item in utterances
                        if item["attribution"] == "assigned" and item["speaker"] is not None}
            for speaker in speakers:
                roles.setdefault(speaker, "patient")
            if len(speakers) == 1:
                model_roles = roles
        decision = None
        signals = ()
        review_issues = ()
        localize = questions_version == BLOCK_QUESTIONS_VERSION
        if checkpoint is not None and checkpoint.data.get("review_code") == "JEV_CONTEXT_LIMIT":
            raise AnalysisRetry("JEV_CONTEXT_LIMIT")
        if not utterances or not any(item["text"].strip() for item in utterances):
            errors.append("TEXT_NOT_EVALUABLE")
        else:
            try:
                review_turns = (
                    self._block_review_turns(fragment, utterances, roles)
                    if not fragment.audio_test and questions_version in CLINICAL_REVIEW_QUESTIONS_VERSIONS else {}
                )
                if checkpoint is not None and "jev_response" in checkpoint.data:
                    decision = JevDecision(**checkpoint.data["jev_response"])
                else:
                    if checkpoint is not None and "jev_pending" in checkpoint.data:
                        raise AnalysisRetry("JEV_SUBMISSION_UNCERTAIN")
                    request_id = (checkpoint.data.get("jev_retry_request_id") if checkpoint is not None else None) or uuid4().hex
                    if plain and (checkpoint is None or not checkpoint.data.get("plain_context_prepared")):
                        boundary = fragment.new_audio_start_sample
                        if boundary == fragment.session_origin_sample:
                            utterances = join_previous(utterances, previous_text, boundary / 16000)
                        if checkpoint is not None:
                            checkpoint.data["utterances"] = utterances
                            checkpoint.data["plain_context_prepared"] = True
                    if checkpoint is not None:
                        checkpoint.data["jev_pending"] = {
                            "analysis_unit": "fragment", "request_id": request_id,
                            "questions_version": questions_version,
                        }
                        checkpoint.save()
                    if plain:
                        current = {"analysis_unit": "fragment", "evidence_scope": PLAIN_TEXT_VERSION,
                                   "text": "\n".join(f"[t{index}] {item['text']}"
                                                     for index, item in enumerate(utterances))}
                    else:
                        current = self._block_current(fragment, utterances, roles, model_roles, review_turns,
                                                      localize=localize)
                    decision = self.analyzer.evaluate(current, [], request_id=request_id)
                    if checkpoint is not None:
                        checkpoint.data["jev_response"] = asdict(decision)
                        checkpoint.save()
                if plain:
                    signals, review_issues = plain_signals(fragment, utterances, decision, threshold)
                    if not signals:
                        errors.extend(issue.code for issue in review_issues)
                    if checkpoint is not None and fragment.new_audio_start_sample is not None:
                        last = utterances[-1]
                        if last["end"] > fragment.new_audio_start_sample / 16000:
                            confirmed = any(signal.start == last["start"] and signal.end == last["end"]
                                            and signal.excerpt == last["text"] for signal in signals)
                            checkpoint.data["text_tail"] = [dict(last, text=last["text"][-500:], confirmed=confirmed)]
                else:
                    signals, block_errors = self._block_signals(fragment, utterances, roles, model_roles,
                                                                decision, threshold, review_turns, localize=localize)
                    errors.extend(block_errors)
            except JevContextLimit as exc:
                if checkpoint is not None:
                    checkpoint.data["jev_retry_request_id"] = checkpoint.data.pop("jev_pending")["request_id"]
                    checkpoint.data["review_code"] = "JEV_CONTEXT_LIMIT"
                    checkpoint.save()
                    raise AnalysisRetry("JEV_CONTEXT_LIMIT") from exc
                errors.append("JEV_CONTEXT_LIMIT")
                self.audit.failure("JEV_CONTEXT_LIMIT", sesion_id=fragment.session_id, sequence=fragment.sequence)
            except ProviderError as exc:
                code = "JEV_SUBMISSION_UNCERTAIN" if isinstance(exc, SubmissionUncertain) else "JEV_FAILED"
                if checkpoint is not None:
                    # Solo un rechazo confirmado permite repetir el mismo bloque.
                    # Conserva su request_id para trazabilidad entre intentos.
                    if not isinstance(exc, SubmissionUncertain):
                        checkpoint.data["jev_retry_request_id"] = checkpoint.data.pop("jev_pending")["request_id"]
                        checkpoint.save()
                    raise AnalysisRetry(code) from exc
                errors.append(code)
                self.audit.failure(code, sesion_id=fragment.session_id, sequence=fragment.sequence)
        state = (AnalysisState.INDETERMINATE if errors else
                 AnalysisState.SIGNAL if signals else AnalysisState.NO_SIGNAL)
        result = AnalysisResult(fragment.session_id, fragment.sequence, state, transcription,
                                signals, () if decision is None else (decision,), tuple(sorted(set(errors))),
                                questions_version=questions_version, review_issues=review_issues)
        if checkpoint is None:
            self.register_signals(fragment, result)
        else:
            request = checkpoint.data.get("jev_pending")
            if request and decision is not None:
                requests = checkpoint.data.setdefault("jev_requests", [])
                if request["request_id"] not in requests:
                    requests.append(request["request_id"])
            checkpoint.data["result"] = {
                "state": result.state, "signals": [asdict(signal) for signal in result.signals],
                "decisions": [asdict(item) for item in result.decisions],
                "error_codes": result.error_codes, "questions_version": result.questions_version,
                "review_issues": [asdict(issue) for issue in result.review_issues],
            }
            checkpoint.save()
            # El resultado y la respuesta ya están persistidos. La recuperación
            # posterior usa result, sin conservar otra copia del bloque completo.
            for key in ("utterances", "roles", "jev_response", "jev_pending", "jev_retry_request_id",
                        "plain_prepared", "plain_context_prepared"):
                checkpoint.data.pop(key, None)
            checkpoint.save()
        return result

    def _process(self, fragment, roles, checkpoint=None, previous_text=()):
        if fragment.session_id not in self.histories and len(self.histories) >= self.max_sessions:
            raise FragmentRejected("Límite de contextos; cierre sesiones terminadas")
        if (fragment.analysis_unit == "utterance" and fragment.sequence > 0
                and fragment.session_id not in self.histories):
            raise AnalysisContextLost("Contexto de sesión no disponible; requiere revisión tras reinicio")
        self.ledger.claim(fragment)
        history = self.histories.setdefault(fragment.session_id, [])
        decisions, signals, errors = [], [], []
        if checkpoint is not None:
            stored_unit = checkpoint.data.setdefault("analysis_unit", fragment.analysis_unit)
            if stored_unit != fragment.analysis_unit:
                raise FragmentRejected("Checkpoint pertenece a otra unidad de análisis")
        threshold = self._threshold(checkpoint)
        questions_version = PLAIN_TEXT_VERSION
        if checkpoint is not None and ("jev_pending" in checkpoint.data or "jev_response" in checkpoint.data):
            questions_version = checkpoint.data.get("jev_pending", {}).get("questions_version", "bloque-signals-1")
        plain = fragment.analysis_unit == "fragment" and questions_version == PLAIN_TEXT_VERSION

        def prepare(words):
            if plain:
                prepared = text_segments(words, fragment.session_origin_sample / 16000, lambda text: redact_for_jev(
                    text, fragment, self.secrets, self.redact_terms))
                if checkpoint is not None:
                    checkpoint.data["plain_prepared"] = True
                return prepared
            if fragment.analysis_unit == "fragment":
                return self._prepare_block(fragment, words)
            return self._prepare_utterances(fragment, words)

        try:
            if checkpoint is None:
                transcription = self.transcriptor.transcribe(fragment)
            elif ("utterances" not in checkpoint.data
                  or checkpoint.data["speechmatics"]["state"] != "deleted"):
                if not plain:
                    checkpoint.data.setdefault("roles", roles)
                transcription = self.transcriptor.transcribe(
                    fragment, checkpoint=checkpoint, prepare=prepare,
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
        if checkpoint is not None:
            utterances = checkpoint.data["utterances"]
            roles = checkpoint.data.get("roles", {})
            if plain and not checkpoint.data.get("plain_prepared"):
                utterances = text_segments(utterances, 0, lambda text: text)
                checkpoint.data["plain_prepared"] = True
        else:
            words = [asdict(word) for word in transcription.words]
            utterances = prepare(words) if fragment.analysis_unit == "fragment" else self._utterances(fragment, words)
        if fragment.analysis_unit == "fragment":
            return self._process_block(fragment, utterances, roles, transcription, errors, checkpoint, threshold,
                                       questions_version, previous_text)
        start = 0
        if checkpoint is not None:
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
                                            "\n".join(h["text"] for h in history), threshold=threshold)
                flags = context_flags(text)
                evaluable = (decision.context == "afirmacion_propia" and role == "patient"
                             and utterance["attribution"] == "assigned"
                             and not set(flags).intersection({"pregunta", "cita", "referencia_a_terceros", "antecedente_temporal"}))
                if not evaluable:
                    errors.append("CONTEXT_NOT_EVALUABLE")
                elif not candidates and any(v >= threshold for v in decision.values[1:]):
                    # Las puertas léxicas pueden abstenerse ante una puntuación alta.
                    errors.append("TEXT_NOT_EVALUABLE")
                else:
                    for candidate in candidates:
                        level = candidate["matrix_level"]
                        severity = review_priority(level)
                        signals.append(Signal(candidate["category_id"], level, severity, text,
                                              utterance["start"], utterance["end"], utterance["speaker"], decision.values[level], threshold))
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
                                tuple(signals), tuple(decisions), tuple(sorted(set(errors))),
                                questions_version=QUESTIONS_VERSION)
        if checkpoint is None:
            self.register_signals(fragment, result)
        else:
            checkpoint.data["result"] = {
                "state": result.state, "signals": [asdict(signal) for signal in result.signals],
                "error_codes": result.error_codes, "questions_version": result.questions_version,
            }
            for key in ("utterances", "roles", "signals", "errors", "next_utterance"):
                checkpoint.data.pop(key, None)
            checkpoint.save()
        return result

    def _threshold(self, checkpoint):
        if checkpoint is not None and "jev_threshold" in checkpoint.data:
            return checkpoint.data["jev_threshold"]
        legacy_started = checkpoint is not None and "roles" in checkpoint.data
        threshold = JEV_DEFAULT_THRESHOLD if legacy_started or self.threshold_loader is None else self.threshold_loader()
        if checkpoint is not None:
            checkpoint.data["jev_threshold"] = threshold
            checkpoint.save()
        return threshold

    def register_signals(self, fragment: Fragment, result: AnalysisResult, *, checkpoint=None) -> None:
        """Se puede reintentar esta entrega interna sin volver a llamar a proveedores."""
        if (result.contract_version != "1.0" or result.session_id != fragment.session_id
                or result.sequence != fragment.sequence):
            raise FragmentRejected("Resultado no corresponde al fragmento")
        if result.state != AnalysisState.SIGNAL or result.error_codes:
            return
        delivery = checkpoint.data.setdefault("delivery", {}) if checkpoint is not None else {}
        test_alerts = []
        plain = result.questions_version == PLAIN_TEXT_VERSION
        groups = (result.signals,) if plain and result.signals else ((signal,) for signal in result.signals)
        for group in groups:
            signal = max(group, key=lambda item: item.matrix_level)
            evidence = self.evidence.setdefault(fragment.session_id, [])
            excerpt = " ".join(signal.excerpt.casefold().split())
            if not plain and fragment.new_audio_start_sample is not None and any(
                    e[0] == signal.category_id and e[1] == excerpt and max(e[2], signal.start) < min(e[3], signal.end)
                    for e in evidence):
                continue
            identity = f"psycode:1.0:{fragment.session_id}:{fragment.sequence}:"
            identity += "texto" if plain else f"{signal.start}:{signal.end}:{signal.category_id}"
            ident = str(uuid5(NAMESPACE_URL, identity))
            def before_notify(alert_id):
                if delivery.get(alert_id) == "sending":
                    if self.alerts.store.has_alert_event(alert_id, "notifications.result"):
                        return False
                    raise AnalysisRetry("NOTIFICATION_UNCERTAIN")
                delivery[alert_id] = "sending"
                checkpoint.save()
                return True

            options = {"before_notify": before_notify} if checkpoint is not None else {}
            origin = "analysis.speechmatics-jev/1.0"
            if fragment.audio_test:
                origin = ORIGEN_PRUEBA_AUDIO
            elif not plain and fragment.analysis_unit == "fragment" and signal.speaker is None:
                origin = ORIGEN_HABLANTE_NO_CONFIRMADO
            try:
                if delivery.get(ident) != "done":
                    analysis = self._signal_details(signal) | {"version": result.questions_version}
                    if plain:
                        analysis["evidencias"] = [self._signal_details(item) | {
                            "texto": item.excerpt,
                            "contexto_anterior": item.context_before,
                            "contexto_posterior": item.context_after,
                        } for item in group]
                        analysis["evidencias_pendientes"] = [asdict(issue) for issue in result.review_issues]
                    self.alerts.register_alert(
                        alerta_id=ident, box=fragment.box, tipo_riesgo="riesgo_suicida",
                        nivel_severidad=signal.severity, fecha_hora=fragment.captured_at,
                        sesion_id=fragment.session_id,
                        origen=origin,
                        descripcion=" ".join(signal.excerpt.split())[:DESCRIPCION_MAX],
                        analisis=analysis,
                        **options)
                    if checkpoint is not None:
                        delivery[ident] = "done"
                        checkpoint.save()
            except AlertAlreadyExists:
                pass
            except PersistenceUnavailable:
                self.audit.failure("ALERT_PERSISTENCE_FAILED", alerta_id=ident,
                                   sesion_id=fragment.session_id, sequence=fragment.sequence)
                raise
            if fragment.audio_test:
                test_alerts.append({
                    "id": ident, "category": signal.category_id, "severity": signal.severity,
                    "start": signal.start, "end": signal.end,
                })
            if not plain and (fragment.audio_test or fragment.new_audio_start_sample is not None):
                evidence.append((signal.category_id, excerpt, signal.start, signal.end))
                evidence[:] = [e for e in evidence if e[3] >= signal.end - 60][-256:]
        if fragment.audio_test and checkpoint is not None:
            checkpoint.data["test_alerts"] = test_alerts

    @staticmethod
    def _signal_details(signal):
        return {
            "categoria": MATRIX["categories"][signal.matrix_level]["name"],
            "nivel_matriz": signal.matrix_level,
            "inicio": signal.start, "fin": signal.end,
            "puntaje": signal.score, "umbral": signal.threshold,
            "plazo": expressed_time(signal.excerpt) if signal.matrix_level in (4, 5) else None,
        }
