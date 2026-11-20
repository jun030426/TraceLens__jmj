"""Offline source-preservation, code gates and real chat HTTP presentation checks."""
import copy
import io
import json
import tempfile
import unittest
import uuid
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from rag_mvp.markdown_tools import slices,parse,render,code_blocks,split_chunk,memory_excerpt,present_turn
from rag_mvp.pipeline import check_answer,render as report
from rag_mvp.corpus import canonical
from video_extraction.shared.common import signature,read
from quiz_mvp.materials import install_material,active_material
from quiz_mvp.store import Store
from quiz_mvp.courses import DEFAULT_OFFERING as OID
from quiz_mvp.server import App,handler


CODE='def calculate(x):\n\tif x < 3:\n\t\treturn "<tag> & 값"  \n\n\treturn x + 1\n'
FENCE='```python\n'+CODE+'```\n'


class CodeText(HTMLParser):
    def __init__(self):super().__init__();self.depth=0;self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if tag=='code':self.depth+=1;self.blocks.append('')
    def handle_endtag(self,tag):
        if tag=='code':self.depth-=1
    def handle_data(self,data):
        if self.depth:self.blocks[-1]+=data


class PreservationTests(unittest.TestCase):
    def test_long_code_kept_whole_with_exact_source_slices(self):
        source='설명\r\n\r\n'+FENCE.replace('\n','\r\n')+'\r\n끝\r\n'
        parts=slices(source,20)
        self.assertEqual(''.join(p['text'] for p in parts),source)
        containing=[p for p in parts if '```python' in p['text']]
        self.assertEqual(len(containing),1);self.assertTrue(containing[0]['oversized_block'])
        self.assertIn(FENCE.replace('\n','\r\n'),containing[0]['text'])
        for p in parts:self.assertEqual(source[p['source_char_start']:p['source_char_end']],p['text']);parse(p['text'])

    def test_nested_list_and_quote_are_not_split_inside_code(self):
        for prefix in ['- 설명\n\n  ','> 설명\n>\n> ']:
            indent='  ' if prefix.startswith('-') else '> '
            nested=prefix+FENCE.replace('\n','\n'+indent).rstrip(' >')
            source='앞\n\n'+nested+'\n\n뒤\n'
            parts=slices(source,15)
            self.assertEqual(''.join(p['text'] for p in parts),source)
            self.assertEqual([c for p in parts for c in code_blocks(p['text'])],[CODE])

    def test_longer_fences_allow_literal_backticks(self):
        source='````markdown\n```python\n    x = 1\n```\n````\n'
        self.assertEqual(len(slices(source,10)),1)
        self.assertEqual(code_blocks(source),['```python\n    x = 1\n```\n'])

    def test_unclosed_or_short_closing_fence_is_rejected(self):
        for source in ['```python\n    x=1','````py\nx=1\n```\n','~~~py\nx=1\n```\n']:
            with self.assertRaisesRegex(ValueError,'unclosed_code_fence'):slices(source)

    def test_unicode_and_tabs_are_not_normalized(self):
        source='```py\n\te\u0301 = "가"\n```\n'
        self.assertEqual(canonical(source),source)
        self.assertEqual(slices(source)[0]['text'],source)

    def test_memory_omits_large_block_instead_of_truncating(self):
        source='설명\n\n'+FENCE+'\n마무리'
        result=memory_excerpt(source,20)
        self.assertNotIn('def calculate',result);self.assertNotIn('```',result)
        self.assertIn('원문은 저장',result);parse(result)
        self.assertEqual(memory_excerpt(source,1000),source)

    def test_bare_code_stays_one_chunk(self):
        c={'id':'code','kind':'code','text':CODE}
        pieces=split_chunk(c,10)
        self.assertEqual(len(pieces),1);self.assertEqual(pieces[0]['text'],CODE)

    def test_real_material_registration_uses_lossless_splitter(self):
        text=('앞 설명입니다.\n\n'*130)+FENCE+('뒤 설명입니다.\n\n'*130)
        c={'id':'source','text':text,'title':'코드 설명','source_file':'lecture.pptx','slide_number':1,
           'quality':'native_xml_text_coverage_checked'}
        corpus={'version':1,'chunks':[c]};corpus['signature']=signature({'version':1,'chunks':[c]})
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);store=Store(out/'learning.sqlite3');install_material(store,out,OID,corpus)
            _,saved=active_material(store,out,OID)
            self.assertGreater(len(saved['chunks']),1)
            self.assertEqual(''.join(x['text'] for x in saved['chunks']),text)
            self.assertEqual([b for x in saved['chunks'] for b in code_blocks(x['text'])],[CODE])
        self.assertEqual(corpus['chunks'][0]['text'],text)


class AnswerCodeTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':FENCE,'source_file':'lecture.pptx','slide_number':1}
        self.candidate={'answerable':True,'claims':[{'text':'핵심 예시:\n\n'+FENCE,'source_id':'s','quote':'def calculate(x):'}],'reason':''}
    def test_exact_complete_example_passes(self):
        self.assertEqual(check_answer(self.candidate,[self.source])['status'],'citation_checked')
    def test_indent_operator_omission_and_unclosed_changes_are_held(self):
        variants=[FENCE.replace('\t','    '),FENCE.replace('x + 1','x - 1'),FENCE.replace('\n\treturn x + 1',''),FENCE[:-4]]
        for variant in variants:
            candidate=copy.deepcopy(self.candidate);candidate['claims'][0]['text']=variant
            self.assertEqual(check_answer(candidate,[self.source])['status'],'held')
    def test_claims_cannot_split_one_code_block(self):
        c=copy.deepcopy(self.candidate);c['claims']=[{**c['claims'][0],'text':FENCE[:30]},{**c['claims'][0],'text':FENCE[30:]}]
        self.assertEqual(check_answer(c,[self.source])['status'],'held')


class PresentationTests(unittest.TestCase):
    def test_render_code_roundtrip_and_markdown_features(self):
        value=render('# 제목\n\n**강조**와 `x`\n\n- 하나\n  - 둘\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n'+FENCE)
        self.assertIn('<h1>',value);self.assertIn('<strong>',value);self.assertIn('<table>',value);self.assertEqual(value.count('<ul>'),2)
        parsed=CodeText();parsed.feed(value);self.assertEqual(parsed.blocks[-1],CODE)
        self.assertIn('data-copy-code',value)
    def test_raw_html_scripts_images_and_unsafe_links_are_inert(self):
        value=render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n![x](https://example.com/x.png)')
        self.assertNotIn('<script>',value);self.assertNotIn('<img',value);self.assertNotIn('href="javascript:',value)
    def test_old_stored_html_is_not_trusted(self):
        turn={'result':{'claims':[{'text':FENCE,'markdown_html':'<script>bad</script>'}]}}
        view=present_turn(turn);self.assertNotIn('<script>',view['result']['claims'][0]['markdown_html'])
        self.assertEqual(turn['result']['claims'][0]['markdown_html'],'<script>bad</script>')
    def test_report_uses_same_renderer_without_api(self):
        with tempfile.TemporaryDirectory() as d:
            report(Path(d),{'question':'예시','claims':[{'text':FENCE,'source_file':'x.pptx','slide_number':1,'quote':'def calculate(x):'}],
                'status':'citation_checked','reason':'test','timing':{'total_seconds':0},'api_stats':{'requests':0,'cache_hits':0}})
            result=(Path(d)/'최소RAG_답변.html').read_text()
            self.assertIn('white-space:pre;',result);parsed=CodeText();parsed.feed(result);self.assertEqual(parsed.blocks,[CODE])
    def test_real_chat_http_returns_safe_rendered_old_answer_and_assets(self):
        with tempfile.TemporaryDirectory() as d:
            app=App(Path(d),offline=True);sid=app.store.student('Markdown 시험')['student_id']
            app.store.enroll(sid,OID)
            question='    def calculate(x):\n\treturn x + 1  \n'
            request_id=str(uuid.uuid4())
            turn,_=app.store.chat_begin(sid,OID,request_id,question)
            self.assertEqual(turn['question'],question)
            retry,created=app.store.chat_begin(sid,OID,request_id,question)
            self.assertFalse(created);self.assertEqual(retry['question'],question)
            app.store.chat_finish(sid,OID,turn['id'],{'offering_id':OID,'status':'citation_checked','claims':[{'text':FENCE,'source_file':'x','slide_number':1,'quote':'def calculate(x):'}]}, {})
            class Connection:
                def __init__(self,raw):self.input=io.BytesIO(raw);self.output=bytearray()
                def makefile(self,*args):return self.input
                def sendall(self,data):self.output.extend(data)
            for path in ['/api/chat','/api/chat/'+turn['id'],'/markdown.css','/markdown.js']:
                conn=Connection(('GET '+path+' HTTP/1.0\r\nHost: 127.0.0.1:8765\r\nX-Student-ID: '+sid+'\r\nX-Offering-ID: '+OID+'\r\n\r\n').encode())
                handler(app)(conn,('127.0.0.1',1),SimpleNamespace(server_port=8765))
                head,body=bytes(conn.output).split(b'\r\n\r\n',1);self.assertIn(b'200',head.split(b'\r\n')[0])
                if path.startswith('/api/'):
                    data=json.loads(body);row=data['turns'][0] if 'turns' in data else data
                    parsed=CodeText();parsed.feed(row['result']['claims'][0]['markdown_html']);self.assertEqual(parsed.blocks,[CODE])


if __name__=='__main__':unittest.main()
