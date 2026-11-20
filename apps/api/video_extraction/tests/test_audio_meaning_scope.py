"""Frozen production evidence and explicit synthetic boundary regression cases."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_meaning_scope as mod
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.archived_audio import replay_fingerprint


class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(replay_fingerprint())
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        with patch.object(mod.Gemini,'call',side_effect=AssertionError('API forbidden')):
            cls.out=cls.root/'policy';cls.p=mod.prepare(cls.out)
            cls.body=cls.root/'body';cls.bp=mod.prepare(cls.body,cls.out,True)
        cls.snap=mod.read(cls.out/'snapshot.json');cls.done=mod.results(cls.out,cls.p)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_real_evidence_releases_only_exact_original(self):
        b=mod.build_bundle(self.snap,self.p['tasks'],self.done)
        self.assertEqual([x['task_id'] for x in b['released_originals']],['repair-553634dcfe5f2be1f831'])
        self.assertEqual(len(b['administrator_holds']),2)
        self.assertEqual(len(b['selected']),266)
        self.assertEqual(b['rows'],self.snap['base_rows'])
        self.assertEqual(len(b['new_restorations']),0)
        ids={x['id'] for x in b['selected']}
        self.assertTrue(all(x['record_id'] not in ids for x in b['administrator_holds']))

    def test_other_holds_block_exact_release(self):
        snap=copy.deepcopy(self.snap)
        target=next(t for t in self.p['tasks'] if t['id']=='repair-553634dcfe5f2be1f831')
        rec=next(r for r in snap['parent_snapshot']['previous_records'] if r['id']==target['target_id'])
        rec['reasons']=['unrelated_content_problem']
        b=mod.build_bundle(snap,self.p['tasks'],self.done)
        self.assertFalse(b['released_originals'])

    def test_body_requires_new_calls_and_pcm_matches(self):
        done=mod.results(self.body,self.bp)
        self.assertEqual(len(done),10)
        t=next(t for t in self.bp['tasks'] if t['mode']=='restore')
        self.assertNotIn(t['id'],done)
        self.assertEqual(t['after'],'요런 주요 메소드를 사용할 수가 있더라')
        self.assertEqual(t['interval'],[359.96,362.8])
        self.assertTrue(t['target_sample_check']['pcm_matches_original'])
        self.assertEqual(self.bp['nominal_api_calls'],2)

    def test_synthetic_new_body_approval_keeps_prefix_separate_and_prior_text(self):
        done=mod.results(self.body,self.bp);t=next(t for t in self.bp['tasks'] if t['mode']=='restore')
        b,r=scoped(t);done[t['id']]={'blind':b,'review':r,'gate':mod.gate(t,b,r)}
        bundle=mod.build_bundle(self.snap,self.bp['tasks'],done)
        self.assertEqual(len(bundle['new_restorations']),1)
        self.assertEqual(bundle['new_restorations'][0]['text'],t['after'])
        self.assertEqual(bundle['boundary_holds'][0]['interval'],[359.4,359.96])
        self.assertTrue(bundle['boundary_holds'][0]['body_restored'])
        self.assertFalse(bundle['boundary_holds'][0]['eligible_for_chunking'])
        self.assertEqual(len(bundle['released_originals']),1)
        byid={r['id']:r for r in bundle['rows']}
        self.assertTrue(all(byid[r['id']]['text']==r['text'] for r in self.snap['base_rows']))
        again=mod.build_bundle(self.snap,self.bp['tasks'],done)
        self.assertEqual(bundle,again)
        # The new body must still fail if its own boundary/content is uncertain.
        b['boundary_clear']=False
        done[t['id']]['gate']=mod.gate(t,b,r)
        bundle=mod.build_bundle(self.snap,self.bp['tasks'],done)
        self.assertFalse(bundle['new_restorations'])
        self.assertFalse(bundle['boundary_holds'][0]['body_restored'])

    def test_content_prefix_cannot_be_dropped_to_force_agreement(self):
        t=next(t for t in self.p['tasks'] if t['mode']=='restore');r=copy.deepcopy(self.done[t['id']])
        r['blind']['text']='사용하지 않으면 요런 주요 메소드를 사용할 수가 있더라'
        with self.assertRaises(ValueError):mod.body_candidate(t,r)

    def test_exact_match_still_needs_full_clear_scope(self):
        t=next(t for t in self.p['tasks'] if t['id']=='repair-553634dcfe5f2be1f831')
        r=copy.deepcopy(self.done[t['id']]);r['review']['target_scope']['boundary_crossing']=True
        self.assertFalse(mod.gate(t,r['blind'],r['review'])['passed'])

if __name__=='__main__':unittest.main()
