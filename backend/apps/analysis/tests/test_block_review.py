from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.analysis.domain import AnalysisState, Fragment, JevDecision, Transcription, Word
from backend.apps.analysis.providers.jev_contract import BLOCK_QUESTIONS_VERSION, DIAGNOSTIC_QUESTIONS_VERSION, block_questions
from backend.apps.analysis.rules import unattributed_levels
from backend.apps.analysis.services import AnalysisService


class ClinicalReviewTests(TestCase):
    def setUp(self):
        self.fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc),
                                 Path("synthetic.wav"), end=5 * 16000, analysis_unit="fragment")
        self.transcriber, self.jev, self.alerts = Mock(), Mock(), Mock()
        self.decision = JevDecision("simulated", "afirmacion_propia", (.1, .9, .9, .9, .9, .9, .9, .9),
                                    10, 1, {str(level): ["t0", "t1"] for level in range(1, 8)})

    def process(self, *words, roles=None, decision=None, threshold=None):
        self.transcriber.transcribe.return_value = Transcription("".join(word.text for word in words), words, "deleted")
        self.jev.evaluate.return_value = decision or self.decision
        service = AnalysisService(self.transcriber, self.jev, Mock(), self.alerts, Mock(),
                                  threshold_loader=lambda: threshold if threshold is not None else .55)
        # Los predicados por voz siguen disponibles para recuperar solicitudes históricas.
        transcription = self.transcriber.transcribe.return_value
        turns = service._prepare_block(self.fragment, [asdict(word) for word in words])
        version = DIAGNOSTIC_QUESTIONS_VERSION if self.fragment.audio_test else BLOCK_QUESTIONS_VERSION
        return service._process_block(self.fragment, turns, roles or {}, transcription, [], None,
                                      threshold if threshold is not None else .55, version, ())

    def test_explicit_affirmative_language_limited_to_the_expressed_level(self):
        for text, levels in (
            ("Ojalá no despertar.", (1,)),
            ("Ojalá no despertara.", (1,)),
            ("No me importaría morir.", (1,)),
            ("No dejo de pensar en suicidarme.", (2,)),
            ("Sí, me quiero matar.", (2,)),
            ("He pensado en quitarme la vida.", (2,)),
            ("He pensado que debería matarme.", (2,)),
            ("Mi hermana me acompañó porque tengo intención de suicidarme.", (4,)),
            ("Nunca he pensado en matarme, pero ojalá no despertara.", (1,)),
            ("He pensado en una forma de suicidarme.", (3,)),
            ("Me voy a matar.", (4,)),
            ("Tengo un plan para suicidarme.", ()),
            ("Tengo un plan para suicidarme y voy a hacerlo.", (5,)),
            ("Hice preparativos para suicidarme.", (6,)),
            ("Acabo de intentar suicidarme.", (7,)),
            ("Esta mañana intenté quitarme la vida.", (7,)),
            ("Hoy intenté quitarme la vida y mi hermana me acompañó.", (7,)),
            ("Sí, intenté quitarme la vida ayer, pero paré y pedí ayuda.", (7,)),
            ("Intenté quitarme la vida y no resultó.", (7,)),
        ):
            with self.subTest(text=text):
                self.assertEqual(unattributed_levels(text), levels)

    def test_context_and_insufficient_text_never_offered_as_review_evidence(self):
        for text in (
            "¿Me quiero matar?", "Por ejemplo, me quiero matar.", "«Me quiero matar».",
            "Mi hermana dijo ‘Qué vergüenza. Me quiero matar. No quiero volver allá’.",
            "Mi hermana dijo: Qué vergüenza. Me quiero matar. No quiero volver allá.",
            "No me quiero matar.", "Nunca he pensado en suicidarme.", "Mi amiga dijo que me quiero matar.",
            "Si me quiero matar, te aviso.", "Me quiero matar de risa.", "Antes me quiero matar.",
            "En 2020 he pensado en suicidarme.", "No puedo más.", "Sí.", "  ",
        ):
            with self.subTest(text=text):
                self.jev.reset_mock()
                result = self.process(Word(text, 0., 1., None))
                self.assertEqual(result.state, AnalysisState.INDETERMINATE)
                if text.strip():
                    self.assertNotIn("review_id", self.jev.evaluate.call_args.args[0]["turns"][0])
                else:
                    self.jev.evaluate.assert_not_called()
        self.alerts.register_alert.assert_not_called()

    def test_confirmed_professional_and_synthetic_unlabeled_voice_cannot_use_review(self):
        word = Word("Me quiero matar.", 0., 1., "S1")
        result = self.process(word, roles={"S1": "professional"})
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertNotIn("review_id", self.jev.evaluate.call_args.args[0]["turns"][0])
        self.fragment = replace(self.fragment, audio_test=True)
        result = self.process(replace(word, speaker=None))
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertNotIn("review_id", self.jev.evaluate.call_args.args[0]["turns"][0])
        self.alerts.register_alert.assert_not_called()

    def test_turn_overlap_negation_split_by_diarization_and_repeated_audio_abstain(self):
        sentence = Word("Me quiero matar.", 0., 1., None)
        for words in (
            (sentence, Word("Texto superpuesto.", .3, .5, "S1")),
            (Word("No", 0., .3, "S1"), replace(sentence, start=.31)),
        ):
            with self.subTest(words=words):
                result = self.process(*words)
                self.assertEqual(result.state, AnalysisState.INDETERMINATE)
                self.assertFalse(any("review_id" in turn for turn in self.jev.evaluate.call_args.args[0]["turns"]))
        self.fragment = replace(self.fragment, new_audio_start_sample=2 * 16000)
        self.assertEqual(self.process(sentence).state, AnalysisState.INDETERMINATE)
        self.assertNotIn("review_id", self.jev.evaluate.call_args.args[0]["turns"][0])
        self.alerts.register_alert.assert_not_called()

    def test_context_score_and_matching_level_and_turn_are_required(self):
        word = Word("Me quiero matar.", 0., 1., "S1")
        for decision in (replace(self.decision, context="cita"),
                         replace(self.decision, evidence_turns={"2": ["t1"]}),
                         replace(self.decision, evidence_turns={"1": ["t0"], "4": ["t0"]})):
            with self.subTest(decision=decision):
                self.assertEqual(self.process(word, decision=decision).state, AnalysisState.INDETERMINATE)
        below = self.process(word, threshold=.91)
        self.assertEqual(below.state, AnalysisState.INDETERMINATE)
        self.assertIn("JEV_BELOW_THRESHOLD", below.error_codes)
        self.alerts.register_alert.assert_not_called()

    def test_review_uses_preceding_turn_to_distinguish_testimony_from_requested_examples(self):
        response = Word("Me quiero matar.", 2., 3., None)
        for prompt, expected in (
            ("¿Puedes dar un ejemplo de algo que diría una persona en una simulación?", AnalysisState.INDETERMINATE),
            ("Repite lo siguiente.", AnalysisState.INDETERMINATE),
            ("¿Puedes dar un ejemplo de cómo te sientes ahora?", AnalysisState.SIGNAL),
        ):
            with self.subTest(prompt=prompt):
                self.alerts.reset_mock()
                result = self.process(Word(prompt, 0., 1., "S1"), response, roles={"S1": "professional"})
                self.assertEqual(result.state, expected)
                sent = self.jev.evaluate.call_args.args[0]["turns"][1]
                self.assertEqual("review_id" in sent, expected == AnalysisState.SIGNAL)
                self.assertEqual(self.alerts.register_alert.call_count, int(expected == AnalysisState.SIGNAL))

    def test_distinct_statements_in_one_block_keep_their_matrix_category_and_priority(self):
        words = (Word("He pensado en quitarme la vida y es algo que me preocupa mucho.", 0., 1., "S1"),
                 Word("Me voy a matar mañana.", 2., 3., "S1"))
        decision = replace(self.decision, values=(0., 0., .85, 0., .91, 0., 0., 0.),
                           evidence_turns={"2": ["t0"], "4": ["t1"]})
        for roles in ({}, {"S1": "patient"}):
            with self.subTest(roles=roles):
                self.alerts.reset_mock()
                result = self.process(*words, roles=roles, decision=decision, threshold=.4)
                self.assertEqual([(s.matrix_level, s.severity) for s in result.signals], [(2, 2), (4, 3)])
                records = [call.kwargs["analisis"] for call in self.alerts.register_alert.call_args_list]
                self.assertEqual([r["plazo"] for r in records], [None, "mañana"])
                self.assertEqual([(r["inicio"], r["puntaje"], r["umbral"]) for r in records],
                                 [(0., .85, .4), (2., .91, .4)])

    def test_attempt_reports_in_one_block_with_or_without_confirmed_role(self):
        texts = ("Hoy intenté quitarme la vida.", "Empecé a suicidarme, pero me detuve.",
                 "Intenté quitarme la vida y alorien me interrumpió.")
        words = tuple(Word(text, i * 1.5, i * 1.5 + 1., "S1") for i, text in enumerate(texts))
        decision = replace(self.decision, values=(0.,) * 7 + (.9,), evidence_turns={"7": ["t0", "t1", "t2"]})
        for roles in ({}, {"S1": "patient"}):
            with self.subTest(roles=roles):
                self.alerts.reset_mock()
                result = self.process(*words, roles=roles, decision=decision, threshold=.4)
                self.assertEqual([(s.excerpt, s.matrix_level, s.severity) for s in result.signals],
                                 [(text, 7, 3) for text in texts])
                self.assertEqual(self.alerts.register_alert.call_count, 3)

    def test_attempt_review_requires_a_personal_affirmation(self):
        for text in ("No intenté quitarme la vida.", "¿Hoy intenté quitarme la vida?",
                     "Ella quiere que intente quitarme la vida.", "Intenté quitarme la vida hace años.",
                     "Intenté quitarme la vida, pero eso fue hace más de diez años.",
                     "Por ejemplo, empecé a suicidarme, pero me detuve.", "Intenté llamar y alguien me interrumpió.",
                     "Mi hermana dijo que yo intenté quitarme la vida.", "Mi primo cree que me quiero matar.",
                     "Intenté matarme de vergüenza.",
                     "Intenté quitarme la vida en mi sueño.", "Quiero morir de risa."):
            with self.subTest(text=text):
                self.assertEqual(unattributed_levels(text), ())

    def test_confirmed_patient_denial_cannot_inherit_positive_score_or_evidence(self):
        words = (
            Word("Hoy intenté quitarme la vida.", 0., 1., "S1"),
            Word("No he intentado suicidarme.", 2., 3., "S1"),
            Word("Tomé la micro y vine para acá. No tengo intención de volver a intentarlo ahora.", 4., 5., "S1"),
        )
        decision = replace(self.decision, evidence_turns={"2": ["t2"], "7": ["t0", "t1"]})
        result = self.process(*words, roles={"S1": "patient"}, decision=decision, threshold=.4)
        self.assertEqual([(s.start, s.matrix_level, s.severity) for s in result.signals], [(0., 7, 3)])
        options = self.jev.evaluate.call_args.args[0]["turns"]
        self.assertEqual([turn.get("id") for turn in options], ["t0", None, None])
        self.alerts.register_alert.assert_called_once()

    def test_confirmed_patient_requires_matching_turn_even_for_an_explicit_attempt(self):
        words = (
            Word("Esta mañana intenté quitarme la vida.", 0., 1., "S1"),
            Word("Dime un poco más.", 2., 3., "S2"),
        )
        for evidence in ({}, {"7": ["t1"]}, {"2": ["t0"]}):
            with self.subTest(evidence=evidence):
                decision = replace(self.decision, evidence_turns=evidence)
                result = self.process(*words, roles={"S1": "patient", "S2": "professional"},
                                      decision=decision, threshold=.4)
                self.assertEqual(result.signals, ())
        self.alerts.register_alert.assert_not_called()

    def test_confirmed_patient_direct_evidence_has_separate_choices_for_each_turn(self):
        questions = block_questions(evidence_texts={
            "t0": "Esta mañana intenté quitarme la vida.",
            "t1": "Ayer intenté quitarme la vida.",
            "t2": "Vine para acá en micro.",
        })
        self.assertEqual(set(questions["evidencia_7_0"]["criteria"]), {"ninguno", "t0"})
        self.assertEqual(set(questions["evidencia_7_1"]["criteria"]), {"ninguno", "t1"})
        self.assertNotIn("evidencia_7_2", questions)
