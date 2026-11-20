"""Offering isolation tests; synthetic fixtures and temporary SQLite databases only."""
import copy
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_mvp import OUTPUT as RAG_OUTPUT
from rag_mvp.corpus import load_corpus
from video_extraction.shared.common import signature
from .courses import DEFAULT_OFFERING, ScopeError
from .generation import demo_quiz, generate, checked_question, QUESTION_SCHEMA
from .materials import install_material, active_material, ScopedRag
from .server import App, handler
from .store import Store


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.out=Path(self.tmp.name);self.now=100000
        self.store=Store(self.out/'learning.sqlite3',lambda:self.now)
        self.corpus=load_corpus(RAG_OUTPUT);self.demo=demo_quiz(self.corpus)
        self.sid=self.store.student('분리 테스트')['student_id']
        self.ids=[]
        # One differing dimension per offering, all using the same concept IDs.
        for code,term,section in [('DS','2026-1','01'),('DS','2026-2','01'),('DS','2026-1','02'),('PY','2026-1','01')]:
            c=self.store.create_course(code,code,term,section);self.ids.append(c['id']);self.store.enroll(self.sid,c['id'])
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,oid):
        q=copy.deepcopy(self.demo);q.update(quiz_id=str(uuid.uuid4()),offering_id=oid)
        q['questions']=q['questions'][:3]
        for item in q['questions']:
            item['concept_id']='stack.pop';item['evidence']['offering_id']=oid
            for s in item['evidence']['sources']:s['offering_id']=oid
        self.store.add_quiz(q,oid);return q
    def solve(self,sid,q,oid,correct=True,ms=5000):
        state=self.store.start(sid,q['quiz_id'],oid)
        for item in q['questions']:
            for kind,dt in [('shown',0),('submit',ms)]:
                self.now+=dt
                state=self.store.event(sid,state['attempt_id'],{'event_id':str(uuid.uuid4()),'kind':kind,
                    'revision':state['revision'],'question_id':item['question_id'],
                    'selected':item['answer_index'] if correct else (item['answer_index']+1)%4},oid)
        return state
    def test_subject_term_section_separate_same_items_and_weakness(self):
        for i,oid in enumerate(self.ids):
            q=self.fixture(oid);self.solve(self.sid,q,oid,correct=i%2==0)
        for i,oid in enumerate(self.ids):
            a=self.store.analysis(self.sid,oid);pop=next(c for c in a['concepts'] if c['concept_id']=='stack.pop')
            self.assertEqual((a['total_responses'],a['unique_items']),(3,3))
            self.assertEqual(pop['correct'],3 if i%2==0 else 0)
            self.assertEqual(pop['status'],'현재 응답에서 안정적' if i%2==0 else '취약 가능성')
            self.assertEqual(len(self.store.quizzes(oid)),1)
        self.assertEqual(self.store.analysis(self.sid,DEFAULT_OFFERING)['total_responses'],0)
    def test_cross_scope_access_events_replay_and_shorts(self):
        a,b=self.ids[:2];q=self.fixture(a);state=self.store.start(self.sid,q['quiz_id'],a)
        payload={'event_id':str(uuid.uuid4()),'kind':'shown','revision':0,'question_id':state['question']['question_id']}
        self.store.event(self.sid,state['attempt_id'],payload,a)
        with self.assertRaises(ScopeError):self.store.start(self.sid,q['quiz_id'],b)
        with self.assertRaises(ValueError):self.store.view(self.sid,state['attempt_id'],b)
        with self.assertRaises(ValueError):self.store.event(self.sid,state['attempt_id'],payload,b)
        self.assertTrue(self.store.shorts_handoff(self.sid,'stack.pop',a)['evidence_snapshots'])
        self.assertEqual(self.store.shorts_handoff(self.sid,'stack.pop',b)['evidence_snapshots'],[])
        outsider=self.store.student('미등록')['student_id']
        with self.assertRaises(ScopeError):self.store.analysis(outsider,a)
        bad=copy.deepcopy(q);bad['quiz_id']=str(uuid.uuid4());bad['questions'][0]['evidence']['sources'][0]['offering_id']=b
        with self.assertRaises(ScopeError):self.store.add_quiz(bad,a)
    def test_peer_time_baseline_does_not_cross_offerings(self):
        a,b=self.ids[:2];qa,qb=self.fixture(a),self.fixture(b)
        for n in range(5):
            sid=self.store.student('기준 '+str(n))['student_id'];self.store.enroll(sid,a)
            self.solve(sid,qa,a,ms=4000)
        self.solve(self.sid,qa,a,ms=12000);self.solve(self.sid,qb,b,ms=12000)
        pop=lambda oid:next(c for c in self.store.analysis(self.sid,oid)['concepts'] if c['concept_id']=='stack.pop')
        self.assertEqual(pop(a)['time_comparisons'],3);self.assertEqual(pop(b)['time_comparisons'],0)
    def test_material_revision_and_strict_source_scope(self):
        a,b=self.ids[:2]
        with self.assertRaises(ValueError):active_material(self.store,self.out,a)
        for oid in [a,b]:install_material(self.store,self.out,oid,self.corpus)
        pa,ca=active_material(self.store,self.out,a);pb,cb=active_material(self.store,self.out,b)
        self.assertNotEqual(pa,pb);self.assertNotEqual(ca['signature'],cb['signature'])
        self.assertTrue(set(x['id'] for x in ca['chunks']).isdisjoint(x['id'] for x in cb['chunks']))
        with self.assertRaises(ScopeError):install_material(self.store,self.out,b,ca)
        invalid=copy.deepcopy(self.corpus);invalid['chunks'][0]['text']='tampered'
        with self.assertRaises(ValueError):install_material(self.store,self.out,a,invalid)
        q=self.fixture(a);state=self.store.start(self.sid,q['quiz_id'],a)
        revised=copy.deepcopy(self.corpus);revised['chunks']=revised['chunks'][:2]
        revised['signature']=signature({'version':1,'chunks':revised['chunks']})
        install_material(self.store,self.out,a,revised)
        self.assertEqual(len(self.store.materials(a)),2);self.assertEqual(len(active_material(self.store,self.out,b)[1]['chunks']),12)
        self.assertEqual(self.store.view(self.sid,state['attempt_id'],a),state)
        with self.store.db() as db:self.assertEqual(self.store._quiz(db,q['quiz_id'],a),q)
    def test_actual_llamaindex_search_is_separate_without_network(self):
        class Embeddings:
            embedding_model='offline-test';dimensions=3
            def embed(self,text,query=False,title=None):return [1.0,0.2,0.1]
        a,b=self.ids[:2]
        for oid in [a,b]:
            c=copy.deepcopy(self.corpus);c['chunks']=c['chunks'][:2]
            c['signature']=signature({'version':1,'chunks':c['chunks']})
            install_material(self.store,self.out,oid,c)
            rag=ScopedRag(self.store,self.out,oid,Embeddings());rag.prepare()
            evidence=rag.retrieve('스택');self.assertTrue(evidence['sources'])
            self.assertEqual(evidence['offering_id'],oid)
            self.assertTrue(all(s['offering_id']==oid for s in evidence['sources']))
        rag=ScopedRag(self.store,self.out,a,Embeddings())
        with patch('quiz_mvp.materials.retrieve_evidence',return_value={'sources':[{'offering_id':b}]}):
            with self.assertRaises(ScopeError):rag.retrieve('스택')
    def test_dynamic_concepts_and_generation_scope_gate(self):
        c=self.store.create_course('OTHER','다른 과목','2026-2','01',{'custom.topic':'독립 개념'})
        self.store.enroll(self.sid,c['id']);self.assertEqual(len(self.store.analysis(self.sid,c['id'])['concepts']),1)
        q=copy.deepcopy(self.demo['questions'][0]);q['concept_id']='custom.topic'
        plain={k:q[k] for k in QUESTION_SCHEMA['properties']}
        checked=checked_question(plain,q['evidence'],'custom.topic',q['difficulty'],c['concepts'])
        self.assertTrue(checked['concept_version'].startswith('catalog-'))
        rag=SimpleNamespace(offering_id=c['id'],concepts=c['concepts'],retrieve=lambda q:{'offering_id':self.ids[0],'sources':[{'offering_id':self.ids[0]}]})
        with self.assertRaises(ValueError):generate(rag,SimpleNamespace())
    def test_generated_custom_course_quiz_keeps_scope_through_storage(self):
        c=self.store.create_course('NEW','새 과목','2026-2','03',{'custom.topic':'독립 개념'})
        oid=c['id'];self.store.enroll(self.sid,oid)
        install_material(self.store,self.out,oid,self.corpus)
        _,corpus=active_material(self.store,self.out,oid)
        demo=demo_quiz(corpus);rag=ScopedRag(self.store,self.out,oid,None)
        class Client:
            answer_model='offline-test';number=0
            def request(self,stage,path,payload,parse):
                if stage=='quiz_generate_v1':
                    q=demo['questions'][self.number];self.number+=1
                    result={k:q[k] for k in QUESTION_SCHEMA['properties']};result['concept_id']='custom.topic'
                else:
                    q=demo['questions'][self.number-1]
                    result={'supported':True,'single_correct':True,'explanation_supported':True,'difficulty_matches':True,
                        'answer_index':q['answer_index'],'reason':'test fixture','explanation':q['explanation'],
                        'source_id':q['source_id'],'quote':q['quote']}
                return parse({'status':'completed','output_text':json.dumps(result)})
        with patch.object(rag,'retrieve',return_value={'offering_id':oid,'schema_version':1,'corpus_version':corpus['signature'],'sources':corpus['chunks']}):
            quiz=generate(rag,Client())
        self.store.add_quiz(quiz,oid)
        self.assertEqual(len(self.store.quizzes(oid)),1)
        self.assertEqual(self.store.quizzes(self.ids[0]),[])
        self.assertEqual(quiz['offering_id'],oid)
        self.assertTrue(quiz['concept_version'].startswith('catalog-'))
        result=self.solve(self.sid,quiz,oid)
        self.assertTrue(result['done']);self.assertEqual(self.store.analysis(self.sid,oid)['total_responses'],5)

    def test_duplicate_offering_and_unknown_catalog_rejected(self):
        with self.assertRaises(ValueError):self.store.create_course(' ds ','자료구조','2026-1','01')
        with self.assertRaises(ValueError):self.store.create_course('X','X','2026-1','01',{})


class MigrationTests(unittest.TestCase):
    def test_v1_backup_preserves_json_digest_and_unfinished_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'learning.sqlite3';q=demo_quiz(load_corpus(RAG_OUTPUT));encoded=json.dumps(q,ensure_ascii=False)
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO meta VALUES ('schema_version','1');
                CREATE TABLE students(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE quizzes(id TEXT PRIMARY KEY,snapshot TEXT NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE attempts(id TEXT PRIMARY KEY,student_id TEXT NOT NULL,quiz_id TEXT NOT NULL,state TEXT NOT NULL);
                CREATE TABLE events(attempt_id TEXT NOT NULL,event_id TEXT NOT NULL,payload_digest TEXT NOT NULL,response TEXT NOT NULL,PRIMARY KEY(attempt_id,event_id));
                CREATE TABLE responses(attempt_id TEXT NOT NULL,question_id TEXT NOT NULL,student_id TEXT NOT NULL,item_key TEXT NOT NULL,concept_id TEXT NOT NULL,recorded_ms INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(attempt_id,question_id));''')
                db.execute('INSERT INTO students VALUES (?,?)',('old-user','이전 학생'))
                db.execute('INSERT INTO quizzes VALUES (?,?,?)',(q['quiz_id'],encoded,signature(q)))
                db.execute('INSERT INTO attempts VALUES (?,?,?,?)',('old-attempt','old-user',q['quiz_id'],json.dumps({'cursor':0,'revision':0,'done':False,'created_ms':100,'timing':None})))
            store=Store(path)
            with store.db() as db:
                row=db.execute('SELECT snapshot,digest,offering_id FROM quizzes').fetchone()
                self.assertEqual(tuple(row),(encoded,signature(q),DEFAULT_OFFERING))
                self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],'2')
            self.assertTrue(path.with_name(path.name+'.pre-course-v2.sqlite3').exists())
            resumed=store.start('old-user',q['quiz_id'],DEFAULT_OFFERING);self.assertEqual(resumed['attempt_id'],'old-attempt')
            Store(path)
            self.assertEqual(len(store.courses('old-user')),1)
            self.assertEqual(store.view('old-user','old-attempt'),resumed)


class ScopedHttpTests(unittest.TestCase):
    def test_scoped_api_and_missing_or_wrong_scope_denied(self):
        with tempfile.TemporaryDirectory() as d:
            app=App(Path(d),offline=True)
            class Connection:
                def __init__(self,raw):self.input=io.BytesIO(raw);self.output=bytearray()
                def makefile(self,*args):return self.input
                def sendall(self,data):self.output.extend(data)
            def req(path,data=None,sid='',oid=''):
                body=b'' if data is None else json.dumps(data).encode()
                lines=[('GET' if data is None else 'POST')+' '+path+' HTTP/1.0','Host: 127.0.0.1:8765',
                    'Content-Type: application/json','Content-Length: '+str(len(body)),'X-Student-ID: '+sid,'X-Offering-ID: '+oid]
                conn=Connection(('\r\n'.join(lines)+'\r\n\r\n').encode()+body)
                handler(app)(conn,('127.0.0.1',1),SimpleNamespace(server_port=8765))
                h,b=bytes(conn.output).split(b'\r\n\r\n',1);return int(h.split()[1]),json.loads(b)
            _,s=req('/api/students',{'name':'API 테스트'});sid=s['student_id']
            self.assertEqual(req('/api/quizzes',sid=sid)[0],403)
            _,c=req('/api/courses',{'subject_code':'CS','subject_name':'자료구조','semester':'2026-2','section':'01'},sid)
            oid=c['id'];self.assertEqual(req('/api/quizzes',sid=sid,oid=oid),(200,[]))
            self.assertEqual(req('/api/materials',sid=sid,oid=oid),(200,[]))
            _,quizzes=req('/api/quizzes',sid=sid,oid=DEFAULT_OFFERING)
            self.assertEqual(req('/api/attempts',{'quiz_id':quizzes[0]['quiz_id']},sid,oid)[0],403)
            _,attempt=req('/api/attempts',{'quiz_id':quizzes[0]['quiz_id']},sid,DEFAULT_OFFERING)
            self.assertNotEqual(req('/api/attempts/'+attempt['attempt_id'],sid=sid,oid=oid)[0],200)
            self.assertEqual(req('/api/materials',{'use_legacy_fixture':True},sid,oid)[0],201)
            self.assertEqual(req('/api/materials',sid=sid,oid=oid)[1][0]['offering_id'],oid)
            app.jobs['secret']={'student_id':sid,'offering_id':DEFAULT_OFFERING,'state':'complete'}
            self.assertNotEqual(req('/api/jobs/secret',sid=sid,oid=oid)[0],200)
            self.assertEqual(req('/api/analysis',sid=sid,oid=oid)[1]['total_responses'],0)
            self.assertEqual(req('/api/shorts',{'concept_id':'stack.pop'},sid,oid)[1]['evidence_snapshots'],[])
            _,s2=req('/api/students',{'name':'미등록'})
            self.assertEqual(req('/api/analysis',sid=s2['student_id'],oid=oid)[0],403)


if __name__=='__main__':unittest.main()
