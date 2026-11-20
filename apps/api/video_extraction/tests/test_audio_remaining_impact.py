import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_remaining_impact as m
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.archived_audio import replay_fingerprint


class RemainingImpactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(replay_fingerprint())
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)/'review'
        with patch.object(m.Gemini,'call',side_effect=AssertionError('no API')):cls.p=m.prepare(cls.out)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def evidence(self,t):
        b,r=scoped(t,text='되겠죠',literal='되겠죠')
        review={k:r[k] for k in ('literal_text','target_scope','target_spans','uncertain','full_target_checked')}
        review.update(impact='low',no_unique_concept_or_step=True,no_number_negation_or_condition_change=True,
            core_instruction_preserved_without_target=True,context_preserves_relation=True,reason='synthetic fixture')
        return b,review

    def test_current_two_low_impact_routed_and_two_unknown_retained(self):
        s=m.read(self.out/'summary.json')
        self.assertEqual(s['new_administrator_holds'],2)
        self.assertEqual(s['administrator_holds_including_previous'],4)
        self.assertEqual(s['ordinary_holds'],2);self.assertEqual(s['impact_unknown'],2)
        self.assertEqual(s['important_error_candidates'],0);self.assertEqual(s['api_attempts'],0)
        folder=Path(m.read(self.out/'latest.json')['manifest']).parent
        original=Path(self.p['source_manifest']).parent
        for name in ('full-transcript.corrected.jsonl','usable-audio.jsonl','usable-records.jsonl','new-restorations.jsonl'):
            self.assertEqual((folder/name).read_bytes(),(original/name).read_bytes())
        records=m.base.load_rows(folder/'audio-records.jsonl')
        for a in self.p['local_assessments']:
            r=next(r for r in records if r['id']==a['record_id'])
            self.assertFalse(r['eligible_for_chunking']);self.assertFalse(any(r['eligible_for_generation'].values()))
        self.assertEqual(len(self.p['tasks']),2);self.assertEqual(self.p['nominal_api_calls'],4)

    def test_unknown_high_disagreement_and_boundary_are_not_downgraded(self):
        t=self.p['tasks'][0]
        for impact in ('high','unknown'):
            b,r=self.evidence(t);r['impact']=impact
            self.assertEqual(m.impact_gate(t,b,r)['route'],'ordinary_hold')
        for field in ('no_unique_concept_or_step','no_number_negation_or_condition_change','core_instruction_preserved_without_target','context_preserves_relation'):
            b,r=self.evidence(t);r[field]=False
            self.assertEqual(m.impact_gate(t,b,r)['route'],'ordinary_hold')
        b,r=self.evidence(t);b['text']='출력';b['target_spans'][0]['text']='출력'
        self.assertEqual(m.impact_gate(t,b,r)['route'],'ordinary_hold')
        b,r=self.evidence(t);b['boundary_clear']=False
        self.assertEqual(m.impact_gate(t,b,r)['route'],'ordinary_hold')

    def test_future_low_impact_only_routes_never_releases_or_rewrites(self):
        done={}
        for t in self.p['tasks']:
            b,r=self.evidence(t);done[t['id']]={'blind':b,'review':r,'gate':m.impact_gate(t,b,r)}
        records,admins,boundaries,audits=m.build(self.p,done)
        self.assertEqual(len(admins),6)
        self.assertEqual(boundaries[0]['status'],'pending_administrator')
        self.assertTrue(boundaries[0]['body_restored'])
        self.assertFalse(boundaries[0]['eligible_for_chunking'])
        original=m.base.load_rows(Path(self.p['source_manifest']).parent/'audio-records.jsonl')
        byid={r['id']:r for r in records}
        for r in original:
            for k in ('observed_text','start_seconds','end_seconds','eligible_for_chunking'):
                self.assertEqual(r[k],byid[r['id']][k])

if __name__=='__main__':unittest.main()
