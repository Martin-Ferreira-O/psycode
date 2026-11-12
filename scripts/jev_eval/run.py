"""Comparación con TypeSafe real y entrega de alertas simulada. Ejecutar como módulo."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import random
from statistics import mean, median
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

from dotenv import dotenv_values
import httpx

from backend.apps.analysis.clients import JevAnalizador
from backend.apps.analysis.domain import Fragment
from backend.apps.analysis.providers.jev_contract import BLOCK_QUESTIONS_VERSION
from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.rules import THRESHOLDS
from backend.apps.analysis.services import AnalysisService

from .cases import CASES, EXTENSION_CASES
from .variants import FOLLOWUP, VARIANTS, previous_context, response_context, revise

MODEL = "jev-1.14.0"


def fixture_items(turns, *, overlap=False):
    return [
        {"speaker": turn[0], "text": turn[1], "start": float(i * 2), "end": float(i * 2 + 1),
         "attribution": "overlap" if overlap else "assigned" if turn[0] else "unknown"}
        for i, turn in enumerate(turns)
    ]


def synthetic_cases(cases=CASES, source="synthetic"):
    for case in cases:
        yield {
            **case,
            "utterances": fixture_items(case["turns"], overlap=case["id"] == "pasivo_voz_superpuesta"),
            "previous_utterances": fixture_items(case["previous"]),
            "actual_roles": ["patient" if (turn[2] if len(turn) == 3 else turn[0]) == "P" else "other"
                             for turn in case["turns"]],
            "source": source,
        }


class ObservedClient:
    """Mismo transporte y validador que producción, con captura de respuestas para la prueba."""

    def __init__(self, client, variant):
        self.client, self.variant = client, variant
        self.attempts = []
        self.response = None

    def request(self, method, url, **kwargs):
        payload = deepcopy(kwargs["json"])
        revise(payload, self.variant)
        kwargs["json"] = payload
        attempt = {"questions": len(payload["questions"])}
        self.attempts.append(attempt)
        attempt["long_context"] = "TypeSafe-Danger-Zone-Long-Context" in kwargs["headers"]
        attempt["payload_sha256"] = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        started = monotonic()
        try:
            response = self.client.request(method, url, **kwargs)
            attempt["status"] = response.status_code
            if response.is_success:
                try:
                    parsed = response.json()
                    self.response = parsed if isinstance(parsed, dict) else None
                except ValueError:
                    pass
            return response
        finally:
            attempt["http_ms"] = round((monotonic() - started) * 1000, 2)


class Experiment:
    def __init__(self, adapter, history):
        self.adapter, self.history = adapter, history
        self.current = None

    def evaluate(self, current, history, *, request_id):
        self.current = current
        return self.adapter.evaluate(current, self.history, request_id=request_id)


def evaluate(case, variant, client, settings, repetition):
    fragment = Fragment(str(uuid4()), 0, "diagnostico", datetime.now(timezone.utc), Path("."),
                        end=case.get("frames", 480000), analysis_unit="fragment",
                        session_origin_sample=int(case.get("offset", 0) * 16000),
                        new_audio_start_sample=case.get("new_audio_start_sample"),
                        audio_test=case["diagnostic"])
    observed = ObservedClient(client, variant)
    history = []
    if variant in {"anterior", "preguntas_anterior", FOLLOWUP}:
        history = previous_context(case["previous_utterances"], case.get("previous_roles", case["roles"]),
                                   boundary=case.get("offset"))
    if variant == FOLLOWUP:
        history = response_context(case, history)
    adapter = Experiment(JevAnalizador(settings, observed), history)
    alerts = Mock()
    service = AnalysisService(Mock(), adapter, Mock(), alerts, Mock())
    started = monotonic()
    result = service._process_block(fragment, case["utterances"], case["roles"], None, [], None)
    elapsed_ms = round((monotonic() - started) * 1000, 2)
    decision = result.decisions[0] if result.decisions else None
    current = adapter.current or {"turns": []}
    raw = observed.response
    roles_by_alias = {}
    for turn, role in zip(current["turns"], case["actual_roles"]):
        if "speaker" in turn:
            roles_by_alias.setdefault(turn["speaker"], set()).add(role)
    return {
        "case": case["id"], "variant": variant, "repetition": repetition, "source": case["source"],
        "gold": case["gold"], "actual_roles": case["actual_roles"],
        "model": raw.get("model") if raw else None,
        "answers": raw.get("answers") if raw else None, "usage": raw.get("usage") if raw else None,
        "turn_speakers": {turn["id"]: turn["speaker"] for turn in current["turns"] if "id" in turn},
        "model_roles": current.get("speaker_roles", {}),
        "actual_roles_by_alias": {alias: sorted(roles) for alias, roles in roles_by_alias.items()},
        "history_turns": len(history), "attempts": observed.attempts, "elapsed_ms": elapsed_ms,
        "state": str(result.state), "errors": result.error_codes, "simulated_alerts": alerts.register_alert.call_count,
        "localized": decision.evidence_turns if decision else {},
        "signal": [{"level": signal.matrix_level, "severity": signal.severity, "start": signal.start, "end": signal.end,
                    "turn": next(f"t{i}" for i, item in enumerate(case["utterances"])
                                 if (item["start"], item["end"], item["speaker"]) ==
                                    (signal.start, signal.end, signal.speaker))}
                   for signal in result.signals],
    }


def percentile95(values):
    return sorted(values)[(95 * len(values) + 99) // 100 - 1]


def metric(rows, level):
    counts = dict(tp=0, fp=0, fn=0, tn=0, none=0, local_evidence_empty=0,
                  local_evidence_on_score_positive_empty=0, choice_errors=0, choice_voice_errors=0,
                  choice_selected=0, choice_exact=0, choice_on_positive_exact=0,
                  local_tp=0, local_fp=0, local_fn=0, local_voice_errors=0)
    for row in rows:
        answers = row["answers"]
        expected = set(row["gold"].get(str(level), row["gold"].get(level, [])))
        predicted = answers[f"signal_{level}"]["noul"] >= THRESHOLDS["candidate"]
        counts[{(True, True): "tp", (True, False): "fp",
                (False, True): "fn", (False, False): "tn"}[predicted, bool(expected)]] += 1
        if level == 0:
            continue
        choices = [value["choice"] for key, value in answers.items() if key.startswith(f"evidencia_{level}_")]
        picks = [int(choice[1:]) for choice in choices if choice != "ninguno"]
        counts["none"] += bool(choices and not picks)
        counts["choice_selected"] += len(picks)
        counts["choice_exact"] += sum(index in expected for index in picks)
        counts["choice_on_positive_exact"] += bool(expected.intersection(picks))
        counts["choice_errors"] += sum(index not in expected for index in picks)
        counts["choice_voice_errors"] += sum(row["actual_roles"][index] != "patient" for index in picks)
        empty = not row["localized"].get(str(level))
        counts["local_evidence_empty"] += empty
        counts["local_evidence_on_score_positive_empty"] += empty and predicted
        signals = [int(signal["turn"][1:]) for signal in row["signal"] if signal["level"] == level]
        matched = any(index in expected for index in signals)
        counts["local_tp"] += matched
        counts["local_fp"] += sum(index not in expected for index in signals)
        counts["local_fn"] += bool(expected and not matched)
        counts["local_voice_errors"] += sum(row["actual_roles"][index] != "patient" for index in signals)
    def ratio(num, den):
        return num / den if den else None
    counts["precision"] = ratio(counts["tp"], counts["tp"] + counts["fp"])
    counts["recall"] = ratio(counts["tp"], counts["tp"] + counts["fn"])
    if level == 0:
        return {k: counts[k] for k in ("tp", "fp", "fn", "tn", "precision", "recall")}
    counts["local_precision"] = ratio(counts["local_tp"], counts["local_tp"] + counts["local_fp"])
    counts["local_recall"] = ratio(counts["local_tp"], counts["local_tp"] + counts["local_fn"])
    return counts


def summarize(rows, variants=VARIANTS):
    successful = [row for row in rows if row["usage"] and row["model"] == MODEL and not set(row["errors"]).intersection(
        {"JEV_CONTEXT_LIMIT", "JEV_SUBMISSION_UNCERTAIN", "JEV_FAILED"})]
    # Solo pares completos, para que los fallos de transporte no beneficien a una variante.
    groups = {}
    for row in successful:
        groups.setdefault((row["source"], row["case"], row["repetition"]), set()).add(row["variant"])
    paired = {key for key, evaluated in groups.items() if evaluated == set(variants)}
    summary = {}
    for source in dict.fromkeys(row["source"] for row in rows):
        summary[source] = {}
        for variant in variants:
            all_items = [row for row in rows if row["variant"] == variant and row["source"] == source]
            items = [row for row in successful if row["variant"] == variant and row["source"] == source
                     and (source, row["case"], row["repetition"]) in paired]
            if not items:
                continue
            summary[source][variant] = {
                "submitted": len(all_items), "paired_evaluated": len(items),
                "http_requests": sum(len(row["attempts"]) for row in all_items),
                "long_context_requests": sum(attempt["long_context"] for row in all_items for attempt in row["attempts"]),
                "mean_questions": mean(row["attempts"][0]["questions"] for row in items),
                "mean_input_tokens": mean(row["usage"]["input_tokens"] for row in items),
                "mean_output_tokens": mean(row["usage"]["output_tokens"] for row in items),
                "median_ms": median(row["elapsed_ms"] for row in items),
                "p95_ms": percentile95([row["elapsed_ms"] for row in items]),
                "median_http_ms": median(row["attempts"][-1]["http_ms"] for row in items),
                "p95_http_ms": percentile95([row["attempts"][-1]["http_ms"] for row in items]),
                "context_uncertain": sum(row["answers"]["context"]["choice"] == "incierto" for row in items),
                "indeterminate": sum(row["state"] == "indeterminado" for row in items),
                "no_choice_offered": sum(not row["turn_speakers"] for row in items),
                "simulated_alerts": sum(row["simulated_alerts"] for row in items),
                # Un solo clip diagnóstico, cortes solapados y roles de audio inciertos.
                **({"levels": {str(level): metric(items, level) for level in range(3)}}
                   if source.startswith("synthetic") else {}),
            }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", required=True, action="store_true", help="Autoriza las solicitudes a TypeSafe.")
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSON nuevo con las respuestas y métricas.")
    parser.add_argument("--diagnostic-cases", type=Path, help="Fixture local de diagnóstico autorizado.")
    parser.add_argument("--diagnostic-only", action="store_true")
    parser.add_argument("--variant", choices=(*VARIANTS, FOLLOWUP), action="append")
    parser.add_argument("--extension", action="store_true", help="Incluye una segunda batería sintética.")
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 6))
    args = parser.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY") or dotenv_values(".env").get("TYPESAFE_API_KEY")
    if not key:
        parser.error("Falta TYPESAFE_API_KEY.")
    cases = [] if args.diagnostic_only else list(synthetic_cases())
    if args.extension:
        cases.extend(synthetic_cases(EXTENSION_CASES, "synthetic_extension"))
    if args.diagnostic_cases:
        cases.extend(json.loads(args.diagnostic_cases.read_text()))
    if not cases:
        parser.error("No hay casos de evaluación.")
    settings = Settings(jev_key=key, jev_provider="typesafe", jev_model=MODEL, external_enabled=True, timeout=40)
    rows = []
    selected = tuple(dict.fromkeys(args.variant or VARIANTS))
    rng = random.Random(1414)
    # Un cliente y una solicitud a la vez. Alternar el orden reduce sesgo de calentamiento.
    args.output.touch(mode=0o600, exist_ok=False)
    with args.output.open("w", encoding="utf-8") as output, httpx.Client(
            headers={"Authorization": f"Bearer {key}"}, timeout=30, trust_env=False) as client:
        for repetition in range(1, args.repeat + 1):
            order = cases.copy()
            rng.shuffle(order)
            for case in order:
                variants = list(selected)
                rng.shuffle(variants)
                for variant in variants:
                    rows.append(evaluate(case, variant, client, settings, repetition))
                print(f"{repetition}/{args.repeat} {case['id']} ({len(rows)} evaluaciones)", flush=True)
        report = {"model": MODEL, "baseline": BLOCK_QUESTIONS_VERSION,
                  "run_at_utc": datetime.now(timezone.utc).isoformat(),
                  "jev": "real", "alert_delivery": "simulated",
                  "summary": summarize(rows, selected), "rows": rows}
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
