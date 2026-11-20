import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, save, signature, digest_file
from video_extraction.shared.gemini import Blocked
from video_extraction.ink.runner.ink_continue_v2 import ROOT, prepare, check_plan, hashes, run, execute, diagnostics_with_pixels
from video_extraction.ink.runner.ink_continue import select_batch
from video_extraction.tests.test_ink_pipeline import fixture, visual
from video_extraction.tests.test_ink_continue import local_stub
from video_extraction.tests.test_ink_policy import audit


def setup(root,count=3):
    tasks=[]
    for n in range(count):
        t=fixture(root,'t'+str(n));t.update(time_seconds=n*20,asr_context=[],priority_score=1)
        tasks.append(t)
    out=root/'out';p=dict(tasks=tasks,batch_size=2,model='fake',code_hashes=hashes(),input_hashes={},
        inherited_pending=[],inherited_administrator_queue=[])
    save(out/'plan.json',p);return out,p


class Fake:
    def __init__(self,stop=None,omit=False,empty=False):
        self.stats={'requests':0};self.calls=[];self.stop=stop;self.omit=omit;self.empty=empty
    def call(self,name,media,prompt,schema):
        self.stats['requests']+=1;self.calls.append((name,prompt))
        if self.stop and self.stop in name:raise Blocked('request_budget_exhausted')
        data=json.loads(prompt.split('DATA:\n',1)[1])
        if name.endswith('_visual'):
            return dict(items=[],links=[],complete=True,notes=[]) if self.empty else visual()
        if name.endswith('_targeted_repair'):return visual()
        if name.endswith('_asr_context'):return dict(bindings=[],concepts=[],word_candidates=[],notes=[])
        a=audit(data['candidate'],data['required_ids'])
        if self.empty and name.endswith('_source_audit'):
            a.update(missing=[dict(description='visible mark',box=dict(left=200,top=200,right=800,bottom=800))],complete=False)
        if self.omit and name.endswith('_source_audit'):a['checks']=[]
        return a


class ImprovedContinuationTests(unittest.TestCase):
    def test_real_queue_359_excludes_all_16_and_carries_pending(self):
        with tempfile.TemporaryDirectory() as tmp,patch('video_extraction.ink.runner.ink_continue_v2.Gemini',side_effect=AssertionError('API forbidden')):
            out=Path(tmp)/'next';s=prepare(ROOT/'outputs/ink-continuation-v1',ROOT/'outputs/ink-source-review-v1',out)
            p=check_plan(out)
            self.assertEqual((s['not_processed'],s['inherited_pending'],s['administrator_entries']),(359,1,9))
            self.assertEqual(len(p['excluded_processed_ids']),16)
            self.assertFalse(set(p['excluded_processed_ids']) & {t['id'] for t in p['tasks']})
            self.assertFalse(p['direct_review_approvals_for_new_data'])
            self.assertTrue(all('human_feedback' not in t for t in p['tasks']))
            self.assertEqual(select_batch(out,p)['ids'][0],'frame-00094-ink-004')

    def test_fresh_items_use_recovery_and_selective_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp),1);data=local_stub(out,p,{'ids':['t0']})['tasks']['t0'];client=Fake(omit=True)
            r=execute(data,out,p,client)
            self.assertTrue(r['active_coverage_complete']);self.assertFalse(r['repair_used'])
            self.assertEqual(client.stats['requests'],3)
            self.assertTrue(any(n.endswith('_fill_ids') for n,_ in client.calls))
            self.assertFalse(r['direct_review_receipts_reused'])

    def test_empty_extraction_independently_scanned_and_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp),1);data=local_stub(out,p,{'ids':['t0']})['tasks']['t0'];client=Fake(empty=True)
            r=execute(data,out,p,client)
            self.assertTrue(r['repair_used']);self.assertIn('__scope__',r['repair_requested_ids'])
            self.assertTrue(r['candidate']['items']);self.assertTrue(r['active_coverage_complete'])

    def test_budget_resume_no_duplicate_extraction_next_batch_only_after_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp));first=Fake(stop='t0_continuation_v2_source_audit')
            with patch('video_extraction.ink.runner.ink_continue_v2.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_continue_v2.Gemini',return_value=first):
                with self.assertRaises(Blocked):run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual(select_batch(out,p)['ids'],['t0','t1'])
            client=Fake()
            with patch('video_extraction.ink.runner.ink_continue_v2.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_continue_v2.Gemini',return_value=client):
                s=run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual((s['processed'],s['not_processed']),(2,1))
            self.assertFalse(any(n.endswith('t0_continuation_v2_visual') for n,_ in client.calls))
            self.assertEqual(select_batch(out,p)['ids'],['t2'])

    def test_local_mode_no_api_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp))
            with patch('video_extraction.ink.runner.ink_continue_v2.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_continue_v2.Gemini',side_effect=AssertionError('API forbidden')):
                s=run(out,Path('.env'),Path('python'),Path('models'),local_only=True)
            self.assertEqual(s['api_requests'],0)

    def test_known_punctuation_probes_run_but_dont_reuse_old_approval(self):
        source=ROOT/'outputs/ink-recovery-v1'
        for tid in ('frame-00094-ink-001','frame-00112-ink-003'):
            p=read(source/'prepared'/(tid+'.json'));r=read(source/'results'/(tid+'.json'));before=copy.deepcopy(r)
            d=diagnostics_with_pixels(p,r)
            rows=[x for x in d.values() if x.get('differences')]
            self.assertTrue(rows)
            for x in rows:
                self.assertTrue(x['pixel_candidates']);self.assertFalse(x['automatic_release'])
                self.assertLessEqual(len(x['pixel_candidates']),12)
                self.assertEqual(x['character_to_pixel_alignment'],'not_confirmed')
            self.assertEqual(r,before)

    def test_old_approval_text_not_in_model_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp),1);data=local_stub(out,p,{'ids':['t0']})['tasks']['t0'];client=Fake()
            execute(data,out,p,client)
            for _,prompt in client.calls:
                self.assertNotIn('user_authorized_direct_source_review',prompt)
                self.assertNotIn('source-reviews.json',prompt)

    def test_boundary_repair_uses_full_source_and_saves_aligned_ocr(self):
        source=ROOT/'outputs/ink-continuation-v1';tid='frame-00011-ink-001'
        data=next(read(f)['tasks'][tid] for f in (source/'batches').glob('*/local.json') if tid in read(f)['tasks'])
        data=copy.deepcopy(data);data['task']['asr_context']=[]
        old=read(source/'results'/(tid+'.json'))
        class BoundaryFake(Fake):
            def call(self,name,media,prompt,schema):
                self.calls.append((name,prompt));self.stats['requests']+=1
                d=json.loads(prompt.split('DATA:\n',1)[1])
                if name.endswith('_visual'):return copy.deepcopy(old['candidate'])
                if name.endswith('_targeted_repair'):
                    v=copy.deepcopy(d['candidate']);t=next(i for i in v['items'] if i['id']=='t1')
                    t.update(text='자료구조와의 연계',box=dict(left=198,top=220,right=366.12,bottom=253.11));return v
                a=audit(d['candidate'],d['required_ids'])
                if name.endswith('_source_audit'):
                    c=next(c for c in a['checks'] if c['id']=='t1');c.update(content='partial',full_text='자료구조와의 연계')
                return a
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);r=execute(data,out,{'test':True},BoundaryFake());p=read(out/'prepared'/(tid+'.json'))
            self.assertTrue(r['repair_used']);self.assertEqual(r['final_view']['crop_in_source'],[0,0,1,1])
            self.assertEqual(p['view'],r['final_view'])
            self.assertLess(p['ocr_coverage']['right']-p['ocr_coverage']['left'],1000)


if __name__=='__main__':unittest.main()
