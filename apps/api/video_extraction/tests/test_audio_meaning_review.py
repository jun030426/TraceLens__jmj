"""Semantic warning policy must never erase source text or substantive differences."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_meaning_review as mod
from video_extraction.tests.test_audio_finalize import fixture
from video_extraction.tests.test_audio_primary_scope import scoped,v4task
from video_extraction.tests.archived_audio import replay_fingerprint


def semantic(t,literal=None):
    b,r=scoped(t,text=literal or t['before'],literal=literal or t['before'])
    s={'literal_text':r['literal_text'],'target_scope':r['target_scope'],'target_spans':r['target_spans'],
       'uncertain':False,'full_target_checked':True,'same_core_meaning':True,
       'numbers_negation_preserved':True,'technical_relations_preserved':True,
       'repetition_nonsemantic':True,'no_missing_core_content':True,
       'categories':['particle'],'reason':'synthetic semantic review, not audio evidence'}
    return b,s


class MeaningReviewTests(unittest.TestCase):
    def task(self,before):
        _,ts=fixture();t=v4task(ts[1]);t.update(before=before,after=before,mode='impact_review');return t

    def test_minor_connector_particle_and_quote_prefix_are_only_conditional_warnings(self):
        for a,b in [('를 썼다는 뜻은','썼다는 뜻은'),('서 그 데이터를 출력','그래서 그 데이터를 출력'),
                    ('라고 하는 부분에 대해서 더 이상','이라고 하는 부분에 대해서 이제 더 이상')]:
            t=self.task(a);blind,review=semantic(t,b)
            self.assertTrue(mod.semantic_gate(t,blind,review)['passed'])
            review['same_core_meaning']=False
            self.assertFalse(mod.semantic_gate(t,blind,review)['passed'])

    def test_numbers_negation_concepts_and_relations_not_normalized_away(self):
        for a,b in [('1.5','15'),('가능하다','불가능하다'),('리스트','집합'),
                    ('두 개를 더한다','세 개를 더한다'),('a+b','a-b')]:
            t=self.task(a);blind,review=semantic(t,b)
            self.assertFalse(mod.semantic_gate(t,blind,review)['passed'])

    def test_short_clip_uncertainty_and_reading_disagreement_stay_held(self):
        t=self.task('되겠죠');b,r=semantic(t);b['text']='결과물을'
        b['target_spans'][0]['text']=b['text']
        self.assertFalse(mod.semantic_gate(t,b,r)['passed'])
        b,r=semantic(t);r['target_scope']['boundary_crossing']=True
        self.assertFalse(mod.semantic_gate(t,b,r)['passed'])

    def test_repetition_can_be_warning_but_never_deleted(self):
        t=self.task('상품은 집합으로 관리');before=copy.deepcopy(t)
        b,r=semantic(t,'상품 상품은 집합으로 관리');r['categories']=['nonsemantic_repetition']
        self.assertTrue(mod.semantic_gate(t,b,r)['passed']);self.assertEqual(t,before)
        r['repetition_nonsemantic']=False
        self.assertFalse(mod.semantic_gate(t,b,r)['passed'])

    def test_numeric_scope_and_missing_span_cannot_be_warning(self):
        t=self.task('를 썼다는 뜻은');b,r=semantic(t,'썼다는 뜻은')
        r['target_spans'][0]['end_seconds']=99
        self.assertFalse(mod.semantic_gate(t,b,r)['passed'])
        b,r=semantic(t,'썼다는 뜻은');r['target_spans']=[]
        self.assertFalse(mod.semantic_gate(t,b,r)['passed'])

    def test_real_v5_snapshot_fake_recheck_restores_only_one_gap_preserves_previous_seven(self):
        self.enterContext(replay_fingerprint())
        # Prior model outcomes are frozen inputs. NEW responses below are explicitly fake.
        with tempfile.TemporaryDirectory() as d,patch.object(mod.Gemini,'call',side_effect=AssertionError('no API')):
            out=Path(d)/'followup';p=mod.prepare(out);snap=mod.read(out/'snapshot.json');done={}
            for t in p['tasks']:
                b,r=semantic(t) if t['mode']=='impact_review' else scoped(t)
                done[t['id']]={'blind':b,'review':r,'gate':mod.gate(t,b,r)}
            before=copy.deepcopy(snap);bundle=mod.build_bundle(snap,p['tasks'],done)
            self.assertEqual(len(bundle['new_restorations']),1)
            self.assertEqual(bundle['new_restorations'][0]['text'],'이라고 하는 요런 주요 메소드를 사용할 수가 있더라')
            self.assertEqual(snap,before)
            actual={r['id']:r for r in bundle['rows']}
            for old in snap['base_rows']:
                self.assertEqual(actual[old['id']]['text'],old['text'])
            self.assertEqual(len(bundle['rows']),len(snap['base_rows'])+1)
            self.assertTrue(all(not r.get('gold_approved') for r in bundle['selected']))
            self.assertTrue(bundle['administrator_holds'])
            admin_ids={r['record_id'] for r in bundle['administrator_holds']}
            self.assertFalse(admin_ids & {r['id'] for r in bundle['selected']})
            self.assertTrue(all(not r['eligible_for_chunking'] for r in bundle['administrator_holds']))
            for t in p['tasks']:
                if t['mode']=='normal_control':
                    done[t['id']]['blind']['uncertain']=True
                    done[t['id']]['gate']=mod.gate(t,done[t['id']]['blind'],done[t['id']]['review'])
            bundle=mod.build_bundle(snap,p['tasks'],done)
            self.assertFalse(bundle['fresh_control_supported']);self.assertFalse(bundle['new_restorations'])
            self.assertFalse(bundle['administrator_holds'])
            self.assertEqual(len(bundle['rows']),len(snap['base_rows']))


if __name__=='__main__':unittest.main()
