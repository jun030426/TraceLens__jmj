import copy
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from rag_mvp import OUTPUT as RAG_OUTPUT
from rag_mvp.corpus import load_corpus
from .generation import demo_quiz, generate, checked_question
from .store import Store, Conflict
from .server import App, handler


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.now=100000
        self.store=Store(self.folder/'db.sqlite3',lambda:self.now)
        self.quiz=demo_quiz(load_corpus(RAG_OUTPUT));self.store.add_quiz(self.quiz)
        self.sid=self.store.student('학생 A')['student_id']
        self.state=self.store.start(self.sid,self.quiz['quiz_id'])
    def tearDown(self):self.temp.cleanup()
    def send(self,kind,delta=0,**extra):
        self.now+=delta
        p={'kind':kind,'event_id':str(uuid.uuid4()),'revision':self.state['revision'],
           'question_id':self.state['question']['question_id'],**extra}
        self.state=self.store.event(self.sid,self.state['attempt_id'],p);return p,self.state
    def test_answers_hidden_until_submission(self):
        self.assertNotIn('answer_index',json.dumps(self.state))
        self.assertNotIn('explanation',json.dumps(self.state))
        self.send('shown');_,r=self.send('submit',5000,selected=0)
        self.assertTrue(r['feedback']['correct']);self.assertIn('source',r['feedback'])
        self.assertNotIn('answer_index',r['question'])
    def test_active_pause_resume_and_heartbeat_gap(self):
        self.send('shown');self.send('pause',5000);self.send('resume',30000)
        _,r=self.send('submit',7000,selected=0)
        self.assertEqual(r['feedback']['active_ms'],12000)
        self.assertEqual(r['feedback']['elapsed_ms'],42000)
        self.assertEqual(r['feedback']['inactive_ms'],30000)
        self.assertTrue(r['feedback']['timing_valid'])
        self.send('shown');_,r=self.send('submit',60000,selected=1)
        self.assertEqual(r['feedback']['active_ms'],15000)
        self.assertEqual(r['feedback']['unknown_ms'],45000)
        self.assertFalse(r['feedback']['timing_valid'])
    def test_duplicate_submit_and_stale_revision(self):
        self.send('shown');aid=self.state['attempt_id'];payload,r=self.send('submit',1000,selected=0)
        replay=self.store.event(self.sid,aid,payload)
        self.assertEqual(r,replay)
        self.assertEqual(self.store.analysis(self.sid)['total_responses'],1)
        with self.assertRaises(Conflict):self.store.event(self.sid,aid,{**payload,'selected':1})
        with self.assertRaises(Conflict):self.store.event(self.sid,aid,{**payload,'event_id':str(uuid.uuid4())})
    def test_refresh_resumes_without_reset(self):
        self.send('shown');self.send('heartbeat',5000)
        resumed=self.store.start(self.sid,self.quiz['quiz_id'])
        self.assertEqual(resumed['attempt_id'],self.state['attempt_id'])
        self.assertEqual(resumed['timing']['active_ms'],5000)
        self.assertEqual(self.store.view(self.sid,resumed['attempt_id']),resumed)
    def test_reject_cross_student_access(self):
        other=self.store.student('학생 B')['student_id']
        with self.assertRaises(ValueError):self.store.view(other,self.state['attempt_id'])
    def test_hint_and_repetition_do_not_inflate_diagnosis(self):
        self.send('shown');self.send('hint');self.send('submit',2000,selected=0)
        a=self.store.analysis(self.sid)['concepts'][0]
        self.assertEqual(a['unique_questions'],0);self.assertEqual(a['hint_excluded'],1)
        for q in self.quiz['questions'][1:]:self.send('shown');self.send('submit',2000,selected=q['answer_index'])
        self.state=self.store.start(self.sid,self.quiz['quiz_id'])
        for q in self.quiz['questions']:self.send('shown');self.send('submit',2000,selected=q['answer_index'])
        a=self.store.analysis(self.sid)
        self.assertEqual(a['total_responses'],10);self.assertEqual(a['unique_items'],5)
        self.assertTrue(all(c['status']=='판단 보류' for c in a['concepts']))
    def test_immutable_snapshots_survive_rag_update(self):
        original=copy.deepcopy(self.quiz);changed=copy.deepcopy(self.quiz)
        changed['origin']='gemini_rag';changed['questions'][0]['answer_index']=2
        with self.assertRaises(Conflict):self.store.add_quiz(changed)
        with patch('rag_mvp.corpus.load_corpus',side_effect=RuntimeError('RAG changed')):
            self.send('shown');_,r=self.send('submit',2000,selected=0)
            self.assertTrue(r['feedback']['correct'])
            self.assertEqual(r['feedback']['corpus_version'],original['questions'][0]['evidence']['corpus_version'])
    def test_short_video_handoff_does_not_render_or_expose_student_id(self):
        request=self.store.shorts_handoff(self.sid,'stack.lifo')
        self.assertFalse(request['video_generated']);self.assertEqual(request['status'],'prepared_only')
        self.assertTrue(request['evidence_snapshots']);self.assertNotIn(self.sid,json.dumps(request))
    def test_clock_rollback_is_flagged(self):
        self.send('shown');_,r=self.send('submit',-1000,selected=0)
        self.assertFalse(r['feedback']['timing_valid']);self.assertEqual(r['feedback']['active_ms'],0)
    def test_time_signal_needs_comparable_evidence(self):
        q=copy.deepcopy(self.quiz);q['quiz_id']='synthetic-timing-fixture';q['questions']=q['questions'][:3]
        for item in q['questions']:item['concept_id']='stack.lifo'
        self.store.add_quiz(q)
        for i in range(6):
            sid=self.sid if i==5 else self.store.student('시간 기준 '+str(i))['student_id']
            s=self.store.start(sid,q['quiz_id'])
            for item in q['questions']:
                for kind,dt in [('shown',0),('submit',12000 if i==5 else 4000)]:
                    self.now+=dt
                    s=self.store.event(sid,s['attempt_id'],{'kind':kind,'event_id':str(uuid.uuid4()),
                        'revision':s['revision'],'question_id':item['question_id'],'selected':item['answer_index']})
        c=self.store.analysis(self.sid)['concepts'][0]
        self.assertEqual(c['unique_questions'],3);self.assertEqual(c['time_comparisons'],3)
        self.assertEqual(c['median_time_ratio'],3);self.assertEqual(c['status'],'정답은 안정적 · 속도 연습 후보')


class GenerationTests(unittest.TestCase):
    def setUp(self):self.corpus=load_corpus(RAG_OUTPUT);self.demo=demo_quiz(self.corpus)
    def test_operator_mismatch_rejected(self):
        q=self.demo['questions'][0];plain={k:q[k] for k in ['stem','options','answer_index','explanation','concept_id','difficulty','difficulty_reason','source_id','quote']}
        plain['quote']='source invented + *'
        with self.assertRaises(ValueError):checked_question(plain,q['evidence'],q['concept_id'],q['difficulty'])
    def test_generation_and_verifier_gate_with_mock_responses(self):
        outer=self
        class Rag:
            def retrieve(self,query):return {'schema_version':1,'corpus_version':'fixture','sources':outer.corpus['chunks']}
        class Client:
            answer_model='test-only';count=0;fail=False
            def request(self,stage,path,payload,parse):
                if stage=='quiz_generate_v1':
                    q=outer.demo['questions'][self.count];self.count+=1
                    result={k:q[k] for k in ['stem','options','answer_index','explanation','hint','concept_id','difficulty','difficulty_reason','source_id','quote']}
                else:
                    data=json.loads(payload['input'][0]['text'])
                    outer.assertNotIn('answer_index',data)
                    outer.assertNotIn('explanation',data)
                    q=outer.demo['questions'][self.count-1]
                    result={'supported':not self.fail,'single_correct':True,'explanation_supported':True,
                            'difficulty_matches':True,'answer_index':q['answer_index'],'reason':'fixture',
                            'hint':q['hint'],'explanation':q['explanation'],'source_id':q['source_id'],'quote':q['quote']}
                return parse({'status':'completed','output_text':json.dumps(result)})
        q=generate(Rag(),Client());self.assertEqual(len(q['questions']),5);self.assertEqual(q['origin'],'gemini_rag')
        bad=Client();bad.fail=True
        with self.assertRaises(ValueError):generate(Rag(),bad)


class HttpTests(unittest.TestCase):
    def test_http_handlers_without_socket_full_quiz(self):
        """Actual request handler and DB, in-memory HTTP streams; no network access."""
        with tempfile.TemporaryDirectory() as d:
            app=App(Path(d),offline=True)
            class Connection:
                def __init__(self,raw):self.input=io.BytesIO(raw);self.output=bytearray()
                def makefile(self,*args):return self.input
                def sendall(self,data):self.output.extend(data)
            def req(path,data=None,sid='',origin=None):
                body=b'' if data is None else json.dumps(data).encode()
                lines=[('GET' if data is None else 'POST')+' '+path+' HTTP/1.0',
                    'Host: 127.0.0.1:8765','Content-Type: application/json',
                    'Content-Length: '+str(len(body)),'X-Student-ID: '+sid,'X-Offering-ID: legacy-stack']
                if origin:lines.append('Origin: '+origin)
                conn=Connection(('\r\n'.join(lines)+'\r\n\r\n').encode()+body)
                handler(app)(conn,('127.0.0.1',9999),SimpleNamespace(server_port=8765))
                headers,raw=bytes(conn.output).split(b'\r\n\r\n',1)
                code=int(headers.split()[1])
                return code,json.loads(raw)
            code,profile=req('/api/students',{'name':'HTTP stream test'});self.assertEqual(code,201)
            sid=profile['student_id'];_,quizzes=req('/api/quizzes',sid=sid)
            _,s=req('/api/attempts',{'quiz_id':quizzes[0]['quiz_id']},sid)
            correct=[0,1,2,3,2]
            for index in range(5):
                self.assertNotIn('answer_index',s['question'])
                for kind in ['shown','submit']:
                    code,s=req('/api/attempts/'+s['attempt_id']+'/events',{
                        'kind':kind,'event_id':str(uuid.uuid4()),'revision':s['revision'],
                        'question_id':s['question']['question_id'],'selected':correct[index]},sid)
                    self.assertEqual(code,200)
            self.assertTrue(s['done']);self.assertEqual(s['summary']['correct'],5)
            _,a=req('/api/analysis',sid=sid);self.assertEqual(a['total_responses'],5)
            code,shorts=req('/api/shorts',{'concept_id':'stack.pop'},sid)
            self.assertEqual(code,201);self.assertFalse(shorts['video_generated'])
            self.assertEqual(req('/api/students',{'name':'reject'},origin='https://example.com')[0],403)
            self.assertEqual(req('/api/generate',{},sid)[0],400)

    def test_browser_api_flow_and_origin_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            app=App(Path(d),offline=True)
            try:server=ThreadingHTTPServer(('127.0.0.1',0),handler(app))
            except PermissionError:
                if os.environ.get('QUIZ_REQUIRE_HTTP')=='1':raise
                self.skipTest('Execution sandbox cannot bind localhost; run in Mac Terminal to verify HTTP')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def request(path,data=None,sid='',origin=None):
                headers={'Content-Type':'application/json','X-Student-ID':sid,'X-Offering-ID':'legacy-stack'}
                if origin:headers['Origin']=origin
                req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
                with urllib.request.urlopen(req) as r:return r.read()
            try:
                self.assertIn('강좌별 학습실',request('/').decode())
                student=json.loads(request('/api/students',{'name':'HTTP 테스트'}))['student_id']
                quiz=json.loads(request('/api/quizzes',sid=student))[0]
                attempt=json.loads(request('/api/attempts',{'quiz_id':quiz['quiz_id']},student))
                self.assertNotIn('answer_index',json.dumps(attempt))
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    request('/api/students',{'name':'blocked'},origin='https://example.com')
                self.assertEqual(caught.exception.code,403)
                with self.assertRaises(urllib.error.HTTPError):request('/api/generate',{},student)
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
