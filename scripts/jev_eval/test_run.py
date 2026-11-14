from copy import deepcopy
import json
from unittest import TestCase

import httpx

from backend.apps.analysis.providers.jev_contract import block_questions
from backend.apps.analysis.providers.settings import Settings

from .run import evaluate, metric, synthetic_cases

MODEL = "jev-1.14.0"
from .variants import FOLLOWUP, previous_context, revise, response_context


class EvaluationTests(TestCase):
    def setUp(self):
        self.cases = {case["id"]: case for case in synthetic_cases()}
        self.settings = Settings(jev_key="dummy", jev_provider="typesafe", jev_model=MODEL, external_enabled=True)

    def test_revised_prompt_keeps_choice_keys_and_points_to_current_turn(self):
        questions = block_questions(("t1",))
        base = {"state": {"current": {"turns": [{"speaker": "voz1"}, {"id": "t1", "speaker": "voz2"}]},
                          "history": []}, "questions": questions}
        revised = deepcopy(base)
        revise(revised, "preguntas")
        self.assertEqual(revised["state"], base["state"])
        self.assertEqual(set(revised["questions"]), set(questions))
        self.assertEqual(set(revised["questions"]["evidencia_1_0"]["criteria"]), {"t1", "ninguno"})
        self.assertIn("current.turns[1]", revised["questions"]["evidencia_1_0"]["criteria"]["t1"])
        self.assertIn("voz2", revised["questions"]["evidencia_1_0"]["criteria"]["t1"])
        untouched = deepcopy(base)
        revise(untouched, FOLLOWUP)
        self.assertEqual(base, untouched)

    def test_previous_context_is_bounded_and_aliases_cannot_be_selected(self):
        case = self.cases["pasivo_cruce_con_interjeccion"]
        previous = previous_context(case["previous_utterances"], case["roles"])
        self.assertEqual(len(previous), 2)
        self.assertEqual({turn["speaker"] for turn in previous}, {"prev_voz1"})
        history = response_context(case, previous)
        self.assertEqual(history, [previous[0]])
        self.assertNotIn("id", history[0])
        self.assertEqual(previous_context(case["previous_utterances"], case["roles"], boundary=20), [])
        compound = self.cases["activo_si_compuesta_cruce"]
        previous = previous_context(compound["previous_utterances"], compound["roles"])
        self.assertEqual(response_context(compound, previous), [])
        unconfirmed = dict(case, roles={"E": "professional"})
        self.assertEqual(response_context(unconfirmed, history), [])
        overlap = dict(case, new_audio_start_sample=16000)
        self.assertEqual(response_context(overlap, history), [])

    @staticmethod
    def response(request):
        payload = json.loads(request.content)
        answers = {}
        for key, question in payload["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.98 if key == "signal_2" else 0.01}
            else:
                options = question["criteria"]
                choice = ("afirmacion_propia" if key == "context" else
                          "t0" if key.startswith("evidencia_2") and "t0" in options else "ninguno")
                answers[key] = {"type": "choice", "choice": choice, "confidence": 1,
                                "probabilities": {option: int(option == choice) for option in options}}
        return httpx.Response(200, json={"model": MODEL, "answers": answers,
                                         "usage": {"input_tokens": 10, "output_tokens": 3}})

    def test_alert_is_simulated_and_evidence_points_to_current_patient_response(self):
        sent = []

        def send(request):
            sent.append(json.loads(request.content))
            return self.response(request)

        case = self.cases["activo_si_cruce"]
        with httpx.Client(transport=httpx.MockTransport(send)) as client:
            row = evaluate(case, FOLLOWUP, client, self.settings, 1)
        self.assertEqual(row["signal"][0]["turn"], "t0")
        self.assertEqual(row["simulated_alerts"], 1)
        self.assertEqual(row["localized"]["2"], ["t0"])
        self.assertEqual(len(row["attempts"]), 1)
        self.assertEqual(set(sent[0]["questions"]["evidencia_2_0"]["criteria"]), {"t0", "ninguno"})
        self.assertEqual(sent[0]["state"]["history"][0]["role"], "professional")

    def test_unconfirmed_clinical_role_never_produces_alert(self):
        case = self.cases["activo_rol_clinico_no_confirmado"]
        with httpx.Client(transport=httpx.MockTransport(self.response)) as client:
            row = evaluate(case, FOLLOWUP, client, self.settings, 1)
        self.assertEqual(row["simulated_alerts"], 0)
        self.assertEqual(row["state"], "indeterminado")
        self.assertEqual(row["turn_speakers"], {})
        self.assertEqual(row["history_turns"], 0)

    def test_metric_separates_category_from_evidence_and_attribution(self):
        with httpx.Client(transport=httpx.MockTransport(self.response)) as client:
            row = evaluate(self.cases["activo_si_cruce"], FOLLOWUP, client, self.settings, 1)
        self.assertEqual(metric([row], 2)["local_tp"], 1)
        row["actual_roles"] = ["other"]
        row["gold"] = {}
        stats = metric([row], 2)
        self.assertEqual(stats["fp"], 1)
        self.assertEqual(stats["choice_voice_errors"], 1)
        self.assertEqual(stats["local_voice_errors"], 1)
