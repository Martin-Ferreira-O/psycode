from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest import TestCase
from dataclasses import replace
from unittest.mock import Mock
from backend.apps.analysis.services import AnalysisService
from backend.apps.analysis.domain import Fragment,Transcription,Word,JevDecision,AnalysisState,AnalysisContextLost

class AudioOverlapTests(TestCase):
    def setUp(self):
        self.transcriptor=Mock();self.analyzer=Mock();self.alerts=Mock()
        self.analyzer.evaluate.return_value=JevDecision('simulated','afirmacion_propia',(.1,.9,.1,.1,.1,.1,.1,.1),1,1)
        self.service=AnalysisService(self.transcriptor,self.analyzer,Mock(),self.alerts,Mock())
        self.fragment=Fragment(str(uuid4()),0,'box-3',datetime.now(timezone.utc),Path('synthetic.wav'),end=160000,new_audio_start_sample=0)
    def words(self,start,end):
        self.transcriptor.transcribe.return_value=Transcription('Ojalá no despertar',(Word('Ojalá no despertar',start,end,'S1'),),'deleted')
    def test_overlap_evidence_has_one_alert_but_distinct_occurrence_has_another(self):
        self.words(9.1,9.9)
        result=self.service.process(self.fragment,roles={'S1':'patient'})
        self.assertEqual(result.state,AnalysisState.SIGNAL)
        self.words(.1,.9)
        next_fragment=replace(self.fragment,sequence=1,session_origin_sample=144000,new_audio_start_sample=160000)
        self.service.process(next_fragment,roles={'S1':'patient'})
        self.assertEqual(self.alerts.register_alert.call_count,1)
        self.words(2,3)
        self.service.process(replace(next_fragment,sequence=2,session_origin_sample=288000,new_audio_start_sample=304000),roles={'S1':'patient'})
        self.assertEqual(self.alerts.register_alert.call_count,2)
    def test_boundary_phrase_keeps_context_and_uses_session_time(self):
        self.words(9.6,10)
        self.service.process(self.fragment,roles={'S1':'patient'})
        self.words(.6,1.8)
        self.service.process(replace(self.fragment,sequence=1,session_origin_sample=144000,new_audio_start_sample=160000),roles={'S1':'patient'})
        current=self.analyzer.evaluate.call_args.args[0]
        self.assertAlmostEqual(current['start'],9.6)
        self.assertAlmostEqual(current['end'],10.8)
        self.assertEqual(self.alerts.register_alert.call_count,1)
    def test_unknown_remains_indeterminate_and_restart_requires_context(self):
        self.words(0,1)
        result=self.service.process(self.fragment)
        self.assertEqual(result.state,AnalysisState.INDETERMINATE)
        self.alerts.register_alert.assert_not_called()
        self.service.close_session(self.fragment.session_id)
        with self.assertRaises(AnalysisContextLost):self.service.process(replace(self.fragment,sequence=1))
