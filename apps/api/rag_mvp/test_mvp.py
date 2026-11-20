"""Offline tests. Synthetic vectors only inside the explicit framework smoke test."""
#자동 테스트. 자료 검증, 검색, 잘못된 인용 차단, API 요청 형식, LlamaIndex 저장·검색 등을 점검
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .corpus import prepare, select_rows, load_corpus
from .pipeline import check_answer
from .providers import Google, normalized_vector
from .retrieval import keyword_search, fuse, build_index, vector_search
from video_extraction.shared.common import read, save
from video_extraction.shared.gemini import Blocked


class CorpusTests(unittest.TestCase):
    def test_original_xml_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);c=prepare(out)
            self.assertEqual(len(c['coverage']),12)
            self.assertTrue(c['chunks'])
            self.assertTrue(all(not x['missing'] for x in c['coverage']))
            self.assertEqual(c['signature'],load_corpus(out)['signature'])
            c['chunks'][0]['text']+='tampered';save(out/'corpus.json',c)
            with self.assertRaisesRegex(ValueError,'integrity'):load_corpus(out)

    def test_excludes_answer_and_uncertain_text(self):
        row={'id':'x','role':'lecture','assets':[],'review_flags':[],'text':'stack + 1','slide_number':1}
        self.assertEqual(select_rows([row],['x'])[0]['text'],'stack + 1')
        for update in ({'role':'evaluation_reference'},{'assets':['image']},{'review_flags':['suspect']},{'text':'[ILLEGIBLE]'}):
            with self.assertRaises(ValueError):select_rows([{**row,**update}],['x'])
        with self.assertRaises(ValueError):select_rows([row,row],['x'])

    def test_actual_keyword_retrieval(self):
        with tempfile.TemporaryDirectory() as d:
            c=prepare(Path(d))
            for q,expected in [('Peek 스택 확인','chapter6-s024'),('Underflow 비어 있는 스택','chapter6-s029'),('Search 탐색 시간 복잡도','chapter6-s028')]:
                hits=keyword_search(c['chunks'],q,4)
                self.assertIn(expected,{h.get('parent_slide_id',h['id']) for h in hits})


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.hit={'id':'s1','text':'계산식은 a + b이다.','source_file':'lecture.pptx','slide_number':1}
        self.good={'answerable':True,'claims':[{'text':'계산식은 a + b입니다.','source_id':'s1','quote':'a + b'}],'reason':''}
    def test_literal_citation(self):
        self.assertEqual(check_answer(self.good,[self.hit])['status'],'citation_checked')
    def test_operator_substitution_held(self):
        self.good['claims'][0]['quote']='a * b'
        self.assertEqual(check_answer(self.good,[self.hit])['status'],'held')
    def test_unknown_source_held(self):
        self.good['claims'][0]['source_id']='s2'
        self.assertEqual(check_answer(self.good,[self.hit])['status'],'held')
    def test_abstention(self):
        r=check_answer({'answerable':False,'claims':[],'reason':'unknown'},[self.hit])
        self.assertEqual(r['status'],'abstained');self.assertEqual(r['claims'],[])
    def test_unknown_debugging_requests_evidence_without_publishing_guessed_fix(self):
        candidate={'answerable':False,'claims':[], 'reason':'추측: 모든 파일을 지우면 해결됩니다.'}
        r=check_answer(candidate,[self.hit],'Python 코드 오류가 왜 나요?')
        self.assertEqual(r['status'],'abstained');self.assertEqual(r['claims'],[])
        self.assertIn('최소 예제',r['reason']);self.assertIn('오류 메시지',r['reason'])
        self.assertNotIn('지우면',r['reason'])
    def test_missing_claims_and_extra_output(self):
        self.good['claims']=[]
        self.assertEqual(check_answer(self.good,[self.hit])['status'],'held')
        with self.assertRaises(ValueError):check_answer({**self.good,'unsupported_answer':'x'},[self.hit])
    def test_fusion_rejects_unknown_source(self):
        with self.assertRaises(ValueError):fuse([self.hit],[{'id':'wrong','vector_score':1}],[])


class ProviderTests(unittest.TestCase):
    def test_vector_validation(self):
        self.assertEqual(normalized_vector([3,4],2),[.6,.8])
        for vector in ([0,0],[1],[float('nan'),1],[True,1]):
            with self.assertRaises(ValueError):normalized_vector(vector,2)
    def test_real_payload_contract_and_cache(self):
        calls=[]
        def transport(req,timeout):
            calls.append(json.loads(req.data));return io.BytesIO(b'{"embedding":{"values":[3,4]}}')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'fake-test-key'}):
            client=Google(Path(d),Path(d)/'.env',dimensions=2,delay=0,transport=transport)
            self.assertEqual(client.embed('a+b',title='Test'),[.6,.8])
            client.embed('a+b',title='Test');client.embed('question',query=True)
            self.assertEqual(len(calls),2);self.assertEqual(client.stats['cache_hits'],1)
            self.assertEqual(calls[0]['content']['parts'][0]['text'],'title: Test | text: a+b')
            self.assertEqual(calls[1]['content']['parts'][0]['text'],'task: question answering | query: question')
            self.assertEqual(calls[0]['embedContentConfig'],{'outputDimensionality':2,'autoTruncate':False})
            for f in (Path(d)/'api-cache').glob('*.json'):self.assertNotIn('fake-test-key',f.read_text())
    def test_budget_stops_before_network(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'fake-test-key'}):
            c=Google(Path(d),Path(d)/'.env',max_calls=0,transport=lambda *a,**k:self.fail('network called'))
            with self.assertRaisesRegex(Blocked,'budget'):c.embed('test')


class FrameworkTests(unittest.TestCase):
    def test_real_llamaindex_persistence_with_synthetic_provider(self):
        try:available=importlib.util.find_spec('llama_index.core') is not None
        except ModuleNotFoundError:available=False
        if not available:
            if os.environ.get('RAG_REQUIRE_FRAMEWORK')=='1':self.fail('LlamaIndex is required in the RAG environment')
            self.skipTest('LlamaIndex not installed; terminal launcher requires this test before API calls')
        class Synthetic:
            embedding_model='synthetic-test-only';dimensions=2
            def __init__(self):self.docs=0;self.queries=0
            def embed(self,text,query=False,title='none'):
                if query:self.queries+=1
                else:self.docs+=1
                return [1.,0.] if 'alpha' in text else [0.,1.]
        c={'signature':'test-corpus','chunks':[{'id':'a','text':'alpha','title':'alpha'},{'id':'b','text':'beta','title':'beta'}]}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);provider=Synthetic()
            build_index(out,c,provider);self.assertEqual(provider.docs,2)
            build_index(out,c,provider);self.assertEqual(provider.docs,2)
            hits=vector_search(out,c,provider,'alpha',1)
            self.assertEqual(hits[0]['id'],'a');self.assertEqual(provider.queries,1)


if __name__=='__main__':unittest.main()
