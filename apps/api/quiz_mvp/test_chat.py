"""Offline tests for persistent scoped chat, personalization inputs and API lifecycle."""
import copy
import io
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_mvp import OUTPUT as RAG_OUTPUT
from rag_mvp.corpus import load_corpus
from video_extraction.shared.gemini import Blocked
from .chat import answer_turn, memory_context, SYSTEM
from .courses import DEFAULT_OFFERING as OID, ScopeError
from .generation import demo_quiz
from .server import App, handler
from .store import Store, Conflict


class Rag:
    def __init__(self,store,out,oid,client):
        self.offering_id=oid;self.context=store.course(oid)
        self.sources=copy.deepcopy(load_corpus(RAG_OUTPUT)['chunks'][:2])
        for s in self.sources:s['offering_id']=oid
        self.version='test-corpus';self.queries=[]
    def prepare(self):pass
    def retrieve(self,query):
        self.queries.append(query)
        return {'sources':self.sources,'offering_id':self.offering_id,'corpus_version':self.version,'schema_version':1}


class Client:
    answer_model='offline-fixture';instances=[]
    def __init__(self,*args,**kw):self.payloads=[];self.bad=False;self.__class__.instances.append(self)
    def request(self,stage,path,payload,parse):
        data=json.loads(payload['input'][0]['text']);self.payloads.append(data)
        source=data['retrieved_excerpts'][0]
        result={'answerable':True,'claims':[{'text':source['text'][:100], 'source_id':source['source_id'],
            'quote':'not a source quote +*' if self.bad else source['text'][:100]}],'reason':'fixture'}
        return parse({'status':'completed','output_text':json.dumps(result)})


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.out=Path(self.temp.name);self.clock=100000
        self.store=Store(self.out/'learning.sqlite3',lambda:self.clock)
        self.sid=self.store.student('학생')['student_id'];self.other=self.store.student('다른 학생')['student_id']
        self.oid2=self.store.create_course('OTHER','다른 과목','2026-2','B')['id'];self.store.enroll(self.sid,self.oid2)
        self.rag=Rag(self.store,self.out,OID,None);self.client=Client()
    def tearDown(self):self.temp.cleanup()
    def begin(self,question='Pop을 설명해 줘',sid=None,oid=OID,key=None):
        return self.store.chat_begin(sid or self.sid,oid,key or str(uuid.uuid4()),question)[0]
    def answer(self,question='Pop을 설명해 줘'):
        t=self.begin(question);answer_turn(self.store,self.sid,OID,t,self.rag,self.client);return self.store.chat_turn(self.sid,OID,t['id'])
    def test_persistence_and_student_course_isolation(self):
        t=self.answer('나만의 Pop 질문')
        self.assertEqual(Store(self.store.path).chat_history(self.sid,OID)['turns'][0],t)
        self.assertEqual(self.store.chat_history(self.other,OID)['turns'],[])
        self.assertEqual(self.store.chat_history(self.sid,self.oid2)['turns'],[])
        for sid,oid in [(self.other,OID),(self.sid,self.oid2)]:
            with self.assertRaises(ScopeError):self.store.chat_turn(sid,oid,t['id'])
        other_rag=Rag(self.store,self.out,self.oid2,None)
        t2=self.begin('다른 과목 질문',oid=self.oid2)
        answer_turn(self.store,self.sid,self.oid2,t2,other_rag,self.client)
        self.assertEqual(self.client.payloads[-1]['history'],[])
        self.assertNotIn('나만의',json.dumps(self.client.payloads[-1],ensure_ascii=False))
    def test_idempotency_pending_conflict_and_restart_recovery(self):
        key=str(uuid.uuid4());t=self.begin(key=key)
        again,created=self.store.chat_begin(self.sid,OID,key,t['question']);self.assertFalse(created);self.assertEqual(t,again)
        with self.assertRaises(Conflict):self.begin('changed',key=key)
        with self.assertRaises(Conflict):self.begin('두 번째 질문')
        self.store.interrupt_pending_chats()
        self.assertEqual(self.store.chat_turn(self.sid,OID,t['id'])['state'],'failed')
        new=self.begin('다시 질문');self.assertNotEqual(new['id'],t['id'])
    def test_history_followup_and_current_corpus_are_separate(self):
        old=self.answer('Pop과 Peek 차이 알려줘')
        self.rag.version='updated-corpus'
        result=self.answer('그 차이를 다시 설명해 줘')
        data=self.client.payloads[-1]
        self.assertEqual(data['history'][0]['question'],old['question'])
        self.assertEqual(data['history'][0]['corpus_version'],'test-corpus')
        self.assertEqual(result['result']['corpus_version'],'updated-corpus')
        self.assertIn(old['question'],self.rag.queries[-1])
        self.assertNotIn(self.sid,json.dumps(data));self.assertNotIn(self.other,json.dumps(data))
        self.assertIn('NOT verified course truth',SYSTEM)
    def test_live_weakness_snapshot_and_sparse_evidence(self):
        before=self.answer()['result']['personalization']['concepts']
        self.assertTrue(all(c['status']=='판단 보류' for c in before))
        quiz=demo_quiz(load_corpus(RAG_OUTPUT));quiz['quiz_id']='three-pop-fixture';quiz['questions']=quiz['questions'][:3]
        for q in quiz['questions']:q['concept_id']='stack.pop'
        self.store.add_quiz(quiz);state=self.store.start(self.sid,quiz['quiz_id'])
        for q in quiz['questions']:
            for kind in ['shown','submit']:
                self.clock+=1000
                state=self.store.event(self.sid,state['attempt_id'],{'event_id':str(uuid.uuid4()),'kind':kind,
                    'revision':state['revision'],'question_id':q['question_id'],'selected':(q['answer_index']+1)%4})
        after=self.answer()['result']['personalization']['concepts']
        pop=next(c for c in after if c['concept_id']=='stack.pop')
        self.assertEqual((pop['unique_questions'],pop['wrong'],pop['status']),(3,3,'취약 가능성'))
        self.assertEqual(self.store.analysis(self.sid,self.oid2)['total_responses'],0)
        self.assertIn('Time alone does not establish weakness',SYSTEM)
    def test_bad_quotes_held_and_not_used_as_memory(self):
        self.client.bad=True;t=self.answer()
        self.assertEqual(t['result']['status'],'held');self.assertEqual(t['result']['claims'],[])
        self.assertEqual(t['result']['sources'],[])
        self.client.bad=False;self.answer('다시 설명해 줘')
        self.assertEqual(self.client.payloads[-1]['history'][0]['answer'],'자료 근거 부족으로 답변 보류')
    def test_cross_course_evidence_rejected_before_generation(self):
        self.rag.sources[0]['offering_id']=self.oid2;t=self.begin()
        with self.assertRaises(ScopeError):answer_turn(self.store,self.sid,OID,t,self.rag,self.client)
        self.assertEqual(self.client.payloads,[])
    def test_pagination_and_bounded_related_memory(self):
        for i in range(34):self.answer('Pop 연산 과거 질문' if i==0 else '별개 질문 '+str(i))
        page=self.store.chat_history(self.sid,OID);older=self.store.chat_history(self.sid,OID,page['next_before'])
        self.assertEqual(len(page['turns']),30);self.assertEqual(len(older['turns']),4)
        rows=self.store.chat_context_rows(self.sid,OID);memory=memory_context(rows,'Pop 연산 궁금해')
        self.assertLessEqual(len(memory),9);self.assertTrue(any(m['question']=='Pop 연산 과거 질문' for m in memory))
        self.assertEqual(len({m['turn_id'] for m in memory}),len(memory))
    def test_empty_retrieval_abstains_without_model_request(self):
        self.rag.sources=[];t=self.answer('Python 코드에서 오류가 나요')
        self.assertEqual(t['result']['status'],'abstained');self.assertEqual(self.client.payloads,[])
        self.assertIn('최소 예제',t['result']['reason'])
        self.assertIn('오류 메시지',t['result']['reason'])


class ChatHttpTests(unittest.TestCase):
    def test_real_handlers_worker_persistence_error_and_scope_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            app=App(Path(d));done=threading.Event()
            original=app.store.chat_finish
            def finish(*args):original(*args);done.set()
            class Connection:
                def __init__(self,raw):self.input=io.BytesIO(raw);self.output=bytearray()
                def makefile(self,*args):return self.input
                def sendall(self,data):self.output.extend(data)
            def req(path,data=None,sid='',oid=OID):
                body=b'' if data is None else json.dumps(data).encode()
                lines=[('GET' if data is None else 'POST')+' '+path+' HTTP/1.0','Host: 127.0.0.1:8765',
                    'Content-Type: application/json','Content-Length: '+str(len(body)),'X-Student-ID: '+sid,'X-Offering-ID: '+oid]
                conn=Connection(('\r\n'.join(lines)+'\r\n\r\n').encode()+body)
                handler(app)(conn,('127.0.0.1',1),SimpleNamespace(server_port=8765))
                head,body=bytes(conn.output).split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(body)
            _,p=req('/api/students',{'name':'채팅 학생'});sid=p['student_id']
            with patch('quiz_mvp.server.Google',Client),patch('quiz_mvp.server.ScopedRag',Rag),patch('quiz_mvp.server.check_worker'),patch.object(app.store,'chat_finish',side_effect=finish):
                data={'question':'Pop을 설명해 줘','request_id':str(uuid.uuid4())}
                code,t=req('/api/chat',data,sid);self.assertEqual(code,202);self.assertTrue(done.wait(5))
                with app.guard:pass # worker released shared inference lock
                self.assertEqual(req('/api/chat/'+t['id'],sid=sid)[1]['state'],'complete')
                code,dup=req('/api/chat',data,sid);self.assertEqual(dup['id'],t['id'])
                self.assertEqual(len(req('/api/chat',sid=sid)[1]['turns']),1)
                self.assertEqual(req('/api/chat',sid=sid,oid='')[0],403)
                other=app.store.student('다른 학생')['student_id']
                self.assertEqual(req('/api/chat/'+t['id'],sid=other)[0],403)
                self.assertEqual(req('/api/chat',sid=other)[1]['turns'],[])
                failed=threading.Event();original_fail=app.store.chat_fail
                def fail(*args):original_fail(*args);failed.set()
                with patch('quiz_mvp.server.answer_turn',side_effect=Blocked('gemini_dns_failed')),patch.object(app.store,'chat_fail',side_effect=fail):
                    _,bad=req('/api/chat',{'question':'실패 테스트','request_id':str(uuid.uuid4())},sid)
                    self.assertTrue(failed.wait(5))
                    with app.guard:pass
                self.assertEqual(req('/api/chat/'+bad['id'],sid=sid)[1]['state'],'failed')
                done.clear();code,last=req('/api/chat',{'question':'복구 테스트','request_id':str(uuid.uuid4())},sid)
                self.assertEqual(code,202);self.assertTrue(done.wait(5))
                with app.guard:pass
            reloaded=App(Path(d),offline=True)
            self.assertEqual(len(reloaded.store.chat_history(sid,OID)['turns']),3)
            with self.assertRaises(ValueError):reloaded.new_chat(sid,OID,{'question':'오프라인','request_id':str(uuid.uuid4())})


if __name__=='__main__':unittest.main()
