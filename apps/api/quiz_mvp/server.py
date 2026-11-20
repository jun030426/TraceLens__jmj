"""Loopback-only development server. No cloud deployment or production authentication."""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from rag_mvp import ROOT, OUTPUT as RAG_OUTPUT
from rag_mvp.corpus import load_corpus
from rag_mvp.markdown_tools import present_turn, asset
from .materials import install_material, ScopedRag
from .courses import DEFAULT_OFFERING, ScopeError
from rag_mvp.providers import Google
from rag_mvp.__main__ import check_worker
from video_extraction.shared.common import save, now
from video_extraction.shared.gemini import Blocked
from .chat import answer_turn
from . import CONCEPTS
from .generation import demo_quiz, generate
from .store import Store, Conflict


class App:
    def __init__(self,out,rag_out=RAG_OUTPUT,offline=False):
        self.out,self.rag_out,self.offline=out,rag_out,offline
        self.store=Store(out/'learning.sqlite3')
        legacy=load_corpus(rag_out)
        self.store.add_quiz(demo_quiz(legacy))
        if not self.store.materials(DEFAULT_OFFERING):
            install_material(self.store,out,DEFAULT_OFFERING,legacy)
        self.jobs={};self.guard=threading.Lock()
        self.store.interrupt_pending_chats()

    def new_chat(self,sid,oid,data):
        request_id,question=data.get('request_id'),data.get('question')
        old=self.store.chat_existing(sid,oid,request_id,question)
        if old:return old
        if self.offline:raise ValueError('오프라인 모드에서는 이전 대화 조회만 가능합니다. 답변은 일반 터미널에서 실행하세요.')
        if not self.guard.acquire(blocking=False):raise Conflict('다른 AI 작업이 진행 중입니다. 완료 후 다시 보내 주세요.')
        try:
            embedding=Google(self.rag_out,ROOT/'.env',max_calls=40,delay=2)
            rag=ScopedRag(self.store,self.out,oid,embedding)
            turn,created=self.store.chat_begin(sid,oid,request_id,question)
            if not created:self.guard.release();return turn
        except Exception:
            self.guard.release();raise
        def work():
            try:
                check_worker();rag.prepare()
                # Personalized response cache is separated from shared material embeddings.
                client=Google(self.out/'chat-cache'/sid/oid,ROOT/'.env',max_calls=3,delay=2)
                answer_turn(self.store,sid,oid,turn,rag,client)
            except (ValueError,RuntimeError,FileNotFoundError) as exc:
                self.store.chat_fail(sid,oid,turn['id'],str(exc)[:300])
            except Exception as exc:
                self.store.chat_fail(sid,oid,turn['id'],'답변 생성 실패: '+type(exc).__name__)
            finally:self.guard.release()
        try:threading.Thread(target=work,daemon=True).start()
        except Exception:
            self.store.chat_fail(sid,oid,turn['id'],'작업 시작 실패. 다시 보내 주세요.');self.guard.release();raise
        return turn

    def new_job(self,sid,concept,oid):
        course=self.store.require_course(sid,oid)
        if self.offline:raise ValueError('오프라인 확인 모드입니다. Gemini 생성은 일반 터미널 실행에서 사용하세요.')
        if concept is not None and concept not in course['concepts']:raise ValueError('알 수 없는 개념입니다.')
        if not self.guard.acquire(blocking=False):raise Conflict('이미 퀴즈를 생성 중입니다. 완료 후 다시 시도하세요.')
        jid=str(uuid.uuid4());job={'job_id':jid,'student_id':sid,'offering_id':oid,'state':'running','message':'생성 준비 중','created_at':now()}
        self.jobs[jid]=job
        def work():
            try:
                check_worker()
                client=Google(self.rag_out,ROOT/'.env',max_calls=40,delay=2)
                rag=ScopedRag(self.store,self.out,oid,client)
                job.update(message='선택한 강좌의 자료 인덱스 준비 중')
                rag.prepare()
                quiz=generate(rag,client,concept,lambda m:job.update(message=m))
                self.store.add_quiz(quiz,oid)
                job.update(state='complete',message='5문항 생성·근거 검사 완료',quiz_id=quiz['quiz_id'],api_stats=client.stats)
            except (ValueError,RuntimeError,FileNotFoundError) as exc:
                # Known errors are messages controlled by our code; never serialize provider credentials.
                job.update(state='failed',message=str(exc)[:300])
            except Exception as exc:
                job.update(state='failed',message='생성 작업 실패: '+type(exc).__name__)
            finally:
                try:save(self.out/'generation-jobs'/(jid+'.json'),job)
                finally:self.guard.release()
        threading.Thread(target=work,daemon=True).start()
        return {'job_id':jid,'state':job['state']}


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):pass
        def send(self,code,data,content_type='application/json; charset=utf-8'):
            raw=json.dumps(data,ensure_ascii=False).encode() if content_type.startswith('application/json') else data
            self.send_response(code)
            self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)

        def do_GET(self):self.route('GET')
        def do_POST(self):self.route('POST')

        def route(self,method):
            try:
                allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
                host=self.headers.get('Host','')
                if host not in allowed:self.send(403,{'error':'로컬 주소만 허용합니다.'});return
                origin=self.headers.get('Origin')
                if origin and origin not in {'http://'+x for x in allowed}:self.send(403,{'error':'다른 사이트의 요청은 허용하지 않습니다.'});return
                path=urlparse(self.path).path
                if method=='GET' and path in ['/markdown.css','/markdown.js']:
                    mime='text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8'
                    self.send(200,asset(path[1:]).encode(),mime);return
                if method=='GET' and path in ['/','/app.js','/style.css']:
                    filename={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
                    mime={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
                    self.send(200,(Path(__file__).parent/'web'/filename).read_bytes(),mime);return
                data={}
                if method=='POST':
                    if not self.headers.get('Content-Type','').startswith('application/json'):raise ValueError('JSON 요청이 필요합니다.')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=(8*1024*1024 if path=='/api/materials' else 16384):raise ValueError('요청 크기가 올바르지 않습니다.')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):raise ValueError('JSON 객체가 필요합니다.')
                if path=='/api/config' and method=='GET':self.send(200,{'concepts':CONCEPTS,'offline':app.offline,'default_offering':DEFAULT_OFFERING,'scope_version':2,'chat_version':1});return
                if path=='/api/students' and method=='POST':self.send(201,app.store.student(data.get('name')));return
                sid=self.headers.get('X-Student-ID','');app.store.profile(sid)
                if path=='/api/courses' and method=='GET':self.send(200,app.store.courses(sid));return
                if path=='/api/courses' and method=='POST':
                    course=app.store.create_course(data.get('subject_code'),data.get('subject_name'),data.get('semester'),data.get('section'),data.get('concepts'))
                    app.store.enroll(sid,course['id']);self.send(201,course);return
                if path=='/api/enrollments' and method=='POST':
                    app.store.enroll(sid,data.get('offering_id'));self.send(201,{'enrolled':True});return
                oid=self.headers.get('X-Offering-ID','');course=app.store.require_course(sid,oid)
                if path=='/api/chat' and method=='GET':
                    before=parse_qs(urlparse(self.path).query).get('before',[None])[0]
                    history=app.store.chat_history(sid,oid,int(before) if before is not None else None)
                    history['turns']=[present_turn(t) for t in history['turns']]
                    self.send(200,history);return
                if path=='/api/chat' and method=='POST':self.send(202,present_turn(app.new_chat(sid,oid,data)));return
                if path.startswith('/api/chat/') and method=='GET':
                    self.send(200,present_turn(app.store.chat_turn(sid,oid,path.split('/')[-1])));return
                if path=='/api/course' and method=='GET':self.send(200,course);return
                if path=='/api/materials' and method=='GET':self.send(200,app.store.materials(oid));return
                if path=='/api/materials' and method=='POST':
                    corpus=load_corpus(app.rag_out) if data.get('use_legacy_fixture') is True else data.get('corpus')
                    self.send(201,install_material(app.store,app.out,oid,corpus));return
                if path=='/api/quizzes' and method=='GET':self.send(200,app.store.quizzes(oid));return
                if path=='/api/generate' and method=='POST':self.send(202,app.new_job(sid,data.get('concept_id'),oid));return
                if path.startswith('/api/jobs/') and method=='GET':
                    job=app.jobs.get(path.split('/')[-1])
                    if job is None or job['student_id']!=sid or job['offering_id']!=oid:raise ValueError('생성 작업을 찾을 수 없습니다. 완료된 문제는 목록에서 확인하세요.')
                    self.send(200,{k:v for k,v in job.items() if k!='student_id'});return
                if path=='/api/attempts' and method=='POST':self.send(201,app.store.start(sid,data.get('quiz_id'),oid));return
                if path.startswith('/api/attempts/'):
                    parts=path.split('/');aid=parts[3]
                    if method=='GET' and len(parts)==4:self.send(200,app.store.view(sid,aid,oid));return
                    if method=='POST' and len(parts)==5 and parts[4]=='events':self.send(200,app.store.event(sid,aid,data,oid));return
                if path=='/api/analysis' and method=='GET':self.send(200,app.store.analysis(sid,oid));return
                if path=='/api/shorts' and method=='POST':
                    request=app.store.shorts_handoff(sid,data.get('concept_id'),oid)
                    save(app.out/'shorts-requests'/(str(uuid.uuid4())+'.json'),request)
                    self.send(201,request);return
                self.send(404,{'error':'경로를 찾을 수 없습니다.'})
            except ScopeError as exc:self.send(403,{'error':str(exc)})
            except Conflict as exc:self.send(409,{'error':str(exc)})
            except (ValueError,KeyError,TypeError) as exc:self.send(400,{'error':str(exc)[:300]})
            except Exception as exc:self.send(500,{'error':'로컬 처리 실패: '+type(exc).__name__})
    return Handler


def serve(out,port=8765,offline=False):
    # Bind before migrating: a second launch must not change the DB beneath an old server.
    server=ThreadingHTTPServer(('127.0.0.1',port),BaseHTTPRequestHandler)
    try:
        app=App(out,offline=offline)
        server.RequestHandlerClass=handler(app)
    except Exception:
        server.server_close();raise
    print(f'퀴즈·학습 분석 화면: http://127.0.0.1:{server.server_port}',flush=True)
    print('종료: Ctrl+C · 학습 기록은 learning.sqlite3에 유지됩니다.',flush=True)
    try:server.serve_forever()
    finally:server.server_close()
