from video_extraction._layout import PROJECT_ROOT
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from video_extraction.shared.common import read, save, digest_file
from video_extraction.shared.correction_gate import enforce, require_gate, nesting_changed, process_guarded, SEPARATOR
from video_extraction.ppt.other_data_guarded import records, report
from video_extraction.ppt import other_data_guarded as runner
from video_extraction.shared.common import signature

ROOT=PROJECT_ROOT
AUDIT=ROOT/'outputs/other-data-source-audit-20261029/audit-findings.json'


def block(text,kind='code',bbox=None):
    return dict(id='b',text=text,kind=kind,bbox=bbox or [0,0,1000,1000],uncertainties=[])


def result(before,after):
    return dict(original=dict(blocks=[before],visuals=[]),final_blocks=[after],visuals=[],
                holds=[],deferred_regions=[],changed_blocks=1,corrections=[],text=after['text'])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'source.png';Image.new('RGB',(300,100),'white').save(self.path)

    def guard(self,b,a,evidence=None):
        return enforce(result(b,a),self.path,evidence or {'reviewed':[],'pixels':[]})

    def test_partial_code_loses_parent_nesting(self):
        for spaces in [2,4,8]:
            b=' '*spaces+'print(x)\n'+' '*spaces+'if x:\n'+' '*(spaces*2)+'f()'
            a='print(x)\nif x:\n'+' '*spaces+'f()'
            g=self.guard(block(b),block(a))
            self.assertEqual(g['final_blocks'][0]['text'],b)
            self.assertTrue(g['holds'])

    def test_consistent_indent_rescale_is_not_blocked(self):
        b='for x in xs:\n    f(x)\n    if x:\n        g(x)\nh()'
        a='for x in xs:\n  f(x)\n  if x:\n    g(x)\nh()'
        self.assertFalse(nesting_changed(b,a));self.assertFalse(self.guard(block(b),block(a))['holds'])

    def test_inner_nesting_loss_is_blocked(self):
        self.assertTrue(nesting_changed('    if x:\n        f()\n    g()', '    if x:\n    f()\n    g()'))

    def test_table_blank_shift_and_extra_cell_blocked(self):
        b=block('| key | A | B |\n| out | | X |','table')
        for a in ['| key | A | B |\n| out | | | X |','| key | A | B |\n| out | X | |']:
            g=self.guard(b,block(a,'table'));self.assertEqual(g['final_blocks'][0]['text'],b['text']);self.assertTrue(g['holds'])

    def test_table_markdown_alignment_not_a_content_change(self):
        b=block('| A | B |\n|---|---|\n| 1 | 2 |','table')
        a=block(b['text'].replace('|---|---|','| :--- | :--- |'),'table')
        self.assertFalse(self.guard(b,a)['holds'])

    def test_geometry_kept_separate_from_valid_text(self):
        b=block('wrong',bbox=[100,100,200,200]);a=block('right',bbox=[100,100,900,900])
        g=self.guard(b,a);self.assertEqual(g['final_blocks'][0]['bbox'],b['bbox'])
        self.assertEqual(g['final_blocks'][0]['text'],'right');self.assertTrue(g['holds'])

    def test_zero_preserved_with_candidate_and_selection_hold(self):
        b=block('x = a[0]');a=block('x = a[o]');g=self.guard(b,a)
        self.assertEqual(g['final_blocks'][0]['text'],b['text'])
        task=dict(id='t',media=str(self.path),source_sha256='x')
        rows=records(task,g);self.assertFalse(rows[0]['eligible_for_chunking'])
        self.assertIn('zero_or_o_unresolved',g['holds'][0]['problems'])

    def test_untrusted_separator_rejected_even_when_model_would_accept(self):
        g=self.guard(block('print("----------")'),block('print("-------------")'))
        self.assertEqual(g['final_blocks'][0]['text'],'print("----------")');self.assertTrue(g['holds'])

    def test_real_pixel_counter_not_hardcoded_and_hash_bound(self):
        im=Image.new('RGB',(300,100),'white');d=ImageDraw.Draw(im)
        for n in range(7):d.rectangle((20+n*10,50,25+n*10,51),fill='black')
        im.save(self.path)
        e={'pixels':[dict(image_sha256=digest_file(self.path),bbox_pixels=[18,48,88,54],thresholds=[80,100,120])],'reviewed':[]}
        g=self.guard(block('----------'),block('-------------'),e)
        self.assertEqual(g['final_blocks'][0]['text'],'-------');self.assertFalse(g['holds'])
        e['pixels'][0]['image_sha256']='wrong'
        self.assertTrue(self.guard(block('----------'),block('-------------'),e)['holds'])

    def test_missing_or_tampered_receipt_cannot_be_selected(self):
        task=dict(id='t',media=str(self.path),source_sha256='x');r=result(block('a'),block('b'))
        with self.assertRaises(ValueError):records(task,r)
        g=enforce(r,self.path);g['final_blocks'][0]['text']='tampered'
        with self.assertRaises(ValueError):records(task,g)

    def test_existing_hold_cannot_be_cleared_by_gate(self):
        r=result(block('a'),block('b'));r['holds']=[dict(target_id='b',reason='original_hold')]
        g=enforce(r,self.path);self.assertIn(r['holds'][0],g['holds'])

    def test_pipeline_final_save_is_guarded_not_model_candidate(self):
        from video_extraction.tests.test_vision_layers import Fixture
        client=Fixture();client.initial['blocks']=[dict(block('old',kind='text'),id='b1')]
        client.initial['visuals']=[]
        with patch('video_extraction.shared.gemini.Gemini.call',side_effect=AssertionError('real API forbidden')):
            frame=dict(id='f',path=str(self.path),time_seconds=0)
            g=process_guarded(frame,[frame],[],Path(self.tmp.name),client)
        require_gate(g,self.path)
        self.assertEqual(read(Path(self.tmp.name)/'vision/f/result.json'),g)
        self.assertNotIn('calculation_gate',read(Path(self.tmp.name)/'model-candidates/vision/f/result.json'))

    def test_reviewed_real_regressions_and_successful_changes(self):
        audit=read(AUDIT);cache={}
        for f in audit['findings']:
            if f['category'] not in ('regression','valid_change','still_wrong'):continue
            tid=f['task_id']
            if tid not in cache:
                r=read(ROOT/'outputs/other-data-v1/results'/f'{tid}.json')
                cache[tid]=enforce(read(r['details']),f['source'])
            b=next(b for b in cache[tid]['final_blocks'] if b['id']==f['block_id'])
            with self.subTest(task=tid,block=f['block_id'],field=f['field']):
                if f['category']=='valid_change':self.assertEqual(b['text'],f['after']['text'])
                elif f['field']=='bbox':self.assertEqual(b['bbox'],f['before']['bbox'])
                elif f['field'] in ('indentation','table_columns'):self.assertEqual(b['text'],f['before']['text'])
                elif f['field']=='separator_count':self.assertEqual([len(m) for m in SEPARATOR.findall(b['text'])],[f['expected']])

    def test_migration_no_api_idempotent_and_budget_resume(self):
        base=Path(self.tmp.name);source=base/'old';out=base/'new';source.mkdir()
        task=dict(id='t',kind='screen',media=str(self.path),source_sha256='s')
        p=dict(tasks=[task,dict(id='a',kind='audio'),dict(id='b',kind='audio')],
               inputs={},derived={},code_hashes={},model='fake')
        save(source/'plan.json',p)
        for n in ['native-documents.jsonl','native-changes.jsonl','native-pending.jsonl']:(source/n).write_text('')
        detail=source/'detail.json';save(detail,result(block('x[0]'),block('x[o]')))
        save(source/'results/t.json',dict(task_id='t',kind='screen',details=str(detail),plan_signature=signature(p)))
        with patch.object(runner,'ROOT',base),patch.object(runner.old,'check_plan',return_value=p),patch.object(runner,'Gemini',side_effect=AssertionError('no API in prepare')):
            prepared=runner.prepare(out,source);self.assertEqual(runner.prepare(out,source),prepared)
        migrated=read(out/'results/t.json');self.assertFalse(migrated['records'][0]['eligible_for_chunking'])
        self.assertEqual(read(source/'detail.json')['final_blocks'][0]['text'],'x[o]')
        class Client:
            def __init__(self,*a,**kw):self.stats={'requests':0}
        def fake_execute(t,o,p,c):
            c.stats['requests']+=1
            return dict(task_id=t['id'],kind='audio',status='checked',changes=0,records=[])
        with patch.object(runner,'ROOT',base),patch.object(runner,'Gemini',Client),patch.object(runner,'execute',side_effect=fake_execute) as execution:
            first=runner.run(out,base/'unused.env',max_calls=1)
            second=runner.run(out,base/'unused.env',max_calls=1)
            self.assertEqual(first['completed_this_run'],['a']);self.assertEqual(first['stop_reason'],'request_budget_exhausted')
            self.assertEqual(second['completed_this_run'],['b']);self.assertEqual(second['stop_reason'],'all_tasks_processed')
            self.assertEqual(execution.call_count,2)


if __name__=='__main__':unittest.main()
