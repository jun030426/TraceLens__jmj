"""Actual common entrypoint, no model/API calls or execution of input programs."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.code.processing import analyze
from video_extraction.pipeline import connected as m
from video_extraction.pipeline import code_workflow
from video_extraction.shared.common import read,save,signature
from video_extraction._layout import PROJECT_ROOT

PYTHON='''# module note
import math

class Box:
    """강의 설명"""
    factor = 2
    # 곱하기 메서드
    @staticmethod
    def multiply(x):
        """함수 설명"""
        return x * 2

# 독립 함수
def identity(x):
\treturn x
'''
JAVA='''package lecture;
import java.util.List;
public class Box {
    private int factor = 2;
    /** 교수님 설명 */
    @Deprecated
    public int multiply(int x) { return x * factor; }
    public String braces() { return "{ not a block }"; }
}
'''


class CodePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.out=self.root/'out';self.py=self.root/'fresh.py';self.py.write_text(PYTHON)
        self.java=self.root/'Fresh.java';self.java.write_text(JAVA)
        self.guard=patch.object(m,'Gemini',side_effect=AssertionError('model API forbidden'));self.guard.start();self.addCleanup(self.guard.stop)
        self.key=patch.object(m,'api_key',side_effect=AssertionError('API credential access forbidden'));self.key.start();self.addCleanup(self.key.stop)

    def prepare(self,*paths):return m.prepare(self.out,list(paths or [self.py]),code_python=PROJECT_ROOT/'.venv-rag/bin/python')
    def run_pipeline(self):return m.run(self.out,self.root/'no-key.env',maximum=0,delay=0,local_only=True)
    def published(self,name):
        manifest=Path(read(self.out/'latest.json')['manifest'])
        return [json.loads(line) for line in (manifest.parent/name).read_text().splitlines()]

    def test_python_source_partition_comments_tabs_and_context(self):
        a=analyze(self.py);self.assertEqual(''.join(p['text'] for p in a['parts']),PYTHON)
        selected=[p for p in a['parts'] if p['eligible']]
        self.assertEqual(len(selected),2);self.assertIn('# 곱하기 메서드',selected[0]['text'])
        self.assertIn('@staticmethod',selected[0]['text']);self.assertIn('"""함수 설명"""',selected[0]['text'])
        self.assertIn('\treturn x',selected[1]['text'])
        self.assertEqual(a['imports'][0]['text'],'import math\n')

    def test_actual_common_prepare_run_resume_and_code_export(self):
        p=self.prepare(self.py,self.java);self.assertEqual([t['kind'] for t in p['tasks']],['code','code'])
        s=self.run_pipeline();self.assertEqual(s['pending'],0);self.assertEqual(s['api_attempts'],0)
        rows=self.published('usable-records.jsonl');self.assertEqual(len(rows),4)
        java=next(r for r in rows if r['language']=='java' and r['symbol_name']=='multiply')
        self.assertIn('/** 교수님 설명 */',java['observed_text']);self.assertIn('private int factor',str(java['class_context']))
        self.assertIn('package lecture;',java['module_context'])
        self.assertTrue(all(r['original_text']==r['observed_text']==r['normalized_text'] for r in rows))
        self.assertTrue(all(not r['concept_ids'] for r in rows))
        corpus=read(read(self.out/'latest.json')['code_corpus']);code_workflow.validate_corpus_selection(corpus)
        self.assertEqual(len(corpus['chunks']),4)
        self.assertTrue(all(c['text'].startswith('```') for c in corpus['chunks']))
        before=read(self.out/'latest.json');self.run_pipeline();self.assertEqual(before,read(self.out/'latest.json'))
        self.assertFalse(self.published('changes.jsonl'));self.assertFalse(self.published('review-required.jsonl'))
        self.assertTrue(self.published('code-context.jsonl'))

    def test_corrupted_source_held_without_repair_or_guessing_low_impact(self):
        self.py.write_text('def broken():\nreturn 1\n');self.java.write_text('class Bad { void f() {')
        self.prepare(self.py,self.java);s=self.run_pipeline()
        self.assertEqual(s['usable_records'],0);self.assertEqual(s['held_records'],2)
        self.assertEqual(s['administrator_holds'],0)
        self.assertFalse(self.published('changes.jsonl'))
        self.assertTrue(all('source_syntax_requires_review' in r['reasons'] for r in self.published('review-required.jsonl')))

    def test_rehashed_false_release_is_blocked_by_source_replay(self):
        self.py.write_text('def broken():\nreturn 1\n');p=self.prepare();self.run_pipeline()
        f=next((self.out/'results').glob('*.json'));r=read(f);r['records'][0]['eligible_for_chunking']=True
        r.pop('payload_hash');r['payload_hash']=signature(r);save(f,r)
        with self.assertRaisesRegex(ValueError,'code_selection_differs_from_source'):m.publish(self.out,p)

    def test_source_change_and_fake_export_are_rejected(self):
        self.prepare();self.run_pipeline();corpus=read(read(self.out/'latest.json')['code_corpus'])
        fake=copy.deepcopy(corpus);fake['chunks'][0]['text']+='changed';fake['signature']=signature({'version':1,'chunks':fake['chunks']})
        with self.assertRaisesRegex(ValueError,'differs_from_common_selection'):code_workflow.validate_corpus_selection(fake)
        self.py.write_text(PYTHON+'# edited\n')
        with self.assertRaisesRegex(ValueError,'bound_source_changed'):m.verify(self.out)

    def test_no_execution_and_unicode_crlf_bom_roundtrip(self):
        sentinel=self.root/'must-not-exist'
        text='def 함수():\r\n\treturn "가"\r\n\nopen('+repr(str(sentinel))+', "w").write("bad")\n'
        self.py.write_bytes(b'\xef\xbb\xbf'+text.encode())
        a=analyze(self.py);self.assertEqual(''.join(p['text'] for p in a['parts']),text)
        self.assertEqual(a['bom_bytes'],3);self.assertFalse(sentinel.exists())

    def test_oversized_function_is_held_whole(self):
        text='def huge():\n'+('    value = 1\n'*1400)
        self.py.write_text(text);a=analyze(self.py)
        self.assertEqual(len(a['parts']),1);self.assertEqual(a['parts'][0]['text'],text)
        self.assertEqual(a['parts'][0]['reason'],'oversized_atomic_code');self.assertFalse(a['parts'][0]['eligible'])

    def test_cr_only_comments_stay_with_python_function(self):
        self.py.write_bytes(b'# comment\rdef f():\r    return 1\r')
        a=analyze(self.py)
        self.assertEqual(a['parts'][0]['text'],'# comment\rdef f():\r    return 1\r')
        self.assertTrue(a['parts'][0]['eligible'])

    def test_java_trailing_comment_not_attached_to_next_method(self):
        self.java.write_text('class Box {\n    void first() {} // first note\n    void second() {}\n}\n')
        self.prepare(self.java);self.run_pipeline()
        rows=self.published('usable-records.jsonl')
        self.assertIn('// first note',next(r['observed_text'] for r in rows if r['symbol_name']=='first'))
        self.assertNotIn('first note',next(r['observed_text'] for r in rows if r['symbol_name']=='second'))

    def test_local_only_mixed_input_does_not_call_visual_model(self):
        from PIL import Image
        image=self.root/'new.png';Image.new('RGB',(10,10),'white').save(image)
        m.prepare(self.out,[self.py,image],model='never-called')
        s=self.run_pipeline();self.assertEqual(s['completed'],1);self.assertEqual(s['pending'],1)
        self.assertEqual(s['api_attempts'],0)

    def test_ordered_example_groups_statements_but_not_definitions(self):
        text='x = []\n# append\nx.append(1)\nprint(x)\n\ndef f():\n    return 2\n\ny=f()\nprint(y)\n'
        self.py.write_text(text);a=analyze(self.py)
        selected=[p for p in a['parts'] if p['eligible']]
        self.assertEqual([p['kind'] for p in selected],['module_example','function','module_example'])
        self.assertEqual([p.get('statement_count') for p in selected],[3,None,2])
        self.assertEqual(''.join(p['text'] for p in a['parts']),text)
        self.assertIn('x.append(1)\nprint(x)',selected[0]['text'])

    def test_trailing_indented_comment_belongs_to_function_not_driver(self):
        self.py.write_text('def f():\n    return 1\n    # 대안 결과 설명\n\nprint(f())\n')
        a=analyze(self.py);function=next(p for p in a['parts'] if p['kind']=='function')
        driver=next(p for p in a['parts'] if p['kind']=='module_example')
        self.assertIn('대안 결과 설명',str(function['comment_context']))
        self.assertNotIn('대안 결과 설명',driver['text']+str(driver['comment_context']))

    def test_detached_example_reference_and_file_fallback_are_explicit(self):
        self.py.write_text('def sum_scores(xs):\n    return sum(xs)\n\n# sum_scores([1, 2])\n\n\n\ndef other():\n    return 0\n')
        a=analyze(self.py);selected=[p for p in a['parts'] if p['eligible']]
        self.assertEqual(selected[0]['comment_context'][0]['relation'],'symbol_reference')
        self.assertFalse(selected[1]['comment_context'])
        self.py.write_text('def f():\n    return 1\n\n\n# 파일 공통 설명\n')
        a=analyze(self.py)
        self.assertEqual(next(p for p in a['parts'] if p['eligible'])['comment_context'][0]['relation'],'file_context')

    def test_java_class_comment_does_not_leak_to_another_class(self):
        self.java.write_text('/* Alpha output explanation */\nclass Alpha { void a() {} }\nclass Beta { void b() {} }\n')
        self.prepare(self.java);self.run_pipeline();rows=self.published('usable-records.jsonl')
        self.assertIn('Alpha output explanation',str(next(r for r in rows if r['symbol_name']=='a')['comment_context']))
        self.assertFalse(next(r for r in rows if r['symbol_name']=='b')['comment_context'])

    def test_large_example_and_large_comment_are_held_not_truncated(self):
        text='x=1\n'*5000;self.py.write_text(text);a=analyze(self.py)
        self.assertEqual(len(a['parts']),1);self.assertEqual(a['parts'][0]['text'],text)
        self.assertFalse(a['parts'][0]['eligible'])
        self.py.write_text('def f():\n    return 1\n\n\n# '+('설명'*9000))
        a=analyze(self.py)
        f=next(p for p in a['parts'] if p['kind']=='function')
        self.assertEqual(f['reason'],'oversized_code_with_comments');self.assertFalse(f['eligible'])

    def test_comment_syntax_inside_literal_is_not_linked(self):
        self.py.write_text('def f():\n    return "# not a comment"\n')
        a=analyze(self.py);self.assertFalse(a['parts'][0]['comment_context'])


if __name__=='__main__':unittest.main()
