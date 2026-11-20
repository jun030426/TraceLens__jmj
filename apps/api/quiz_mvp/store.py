"""SQLite repository: immutable question snapshots, idempotent responses and server time."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from statistics import median

from video_extraction.shared.common import signature, now
from . import CONCEPTS, ANALYSIS_VERSION
from .courses import CourseStore, DEFAULT_OFFERING, ScopeError, migrate_courses


class Conflict(ValueError): pass


from .chat_store import ChatStore, init_chat


class Store(CourseStore, ChatStore):
    def __init__(self, path, clock=lambda: int(time.time()*1000)):
        self.path, self.clock = path, clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('schema_version','1');
            CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quizzes (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, student_id TEXT NOT NULL,
                quiz_id TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (attempt_id TEXT NOT NULL, event_id TEXT NOT NULL,
                payload_digest TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(attempt_id,event_id));
            CREATE TABLE IF NOT EXISTS responses (attempt_id TEXT NOT NULL, question_id TEXT NOT NULL,
                student_id TEXT NOT NULL, item_key TEXT NOT NULL, concept_id TEXT NOT NULL,
                recorded_ms INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(attempt_id,question_id));
            CREATE INDEX IF NOT EXISTS response_student ON responses(student_id, recorded_ms);
            ''')
            migrate_courses(db,path)
        with self.db() as db:init_chat(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()

    def student(self, name):
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 30: raise ValueError('이름은 1~30자로 입력하세요.')
        sid = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO students VALUES (?,?)',(sid,name.strip()))
            db.execute('INSERT INTO enrollments VALUES (?,?)',(sid,DEFAULT_OFFERING))
        return {'student_id': sid, 'name': name.strip()}

    def profile(self, sid):
        with self.db() as db:
            row=db.execute('SELECT * FROM students WHERE id=?',(sid,)).fetchone()
            if row is None: raise ValueError('학습자를 먼저 만들어 주세요.')
            return dict(row)

    def add_quiz(self, quiz, offering_id=DEFAULT_OFFERING):
        course=self.course(offering_id)
        if quiz.get('offering_id',offering_id)!=offering_id:raise ScopeError('다른 강좌의 퀴즈입니다.')
        for item in quiz['questions']:
            if item['concept_id'] not in course['concepts']:raise ScopeError('강좌에 등록되지 않은 개념입니다.')
            evidence=item['evidence']
            if evidence.get('offering_id',DEFAULT_OFFERING)!=offering_id:raise ScopeError('출제 근거의 강좌가 다릅니다.')
            if any(x.get('offering_id',DEFAULT_OFFERING)!=offering_id for x in evidence['sources']):raise ScopeError('다른 강좌의 근거가 포함됐습니다.')
        with self.db() as db:
            old=db.execute('SELECT digest,offering_id FROM quizzes WHERE id=?',(quiz['quiz_id'],)).fetchone()
            if old:
                if old['offering_id']!=offering_id:raise ScopeError('다른 강좌의 퀴즈 ID입니다.')
                if quiz['origin']=='manual_demo': return quiz['quiz_id']
                if old[0]!=signature(quiz): raise Conflict('기존 문제 세트를 덮어쓸 수 없습니다.')
            else: db.execute('INSERT INTO quizzes (id,snapshot,digest,offering_id) VALUES (?,?,?,?)',(quiz['quiz_id'],json.dumps(quiz,ensure_ascii=False),signature(quiz),offering_id))
        return quiz['quiz_id']

    def quizzes(self, offering_id=DEFAULT_OFFERING):
        self.course(offering_id)
        with self.db() as db:
            return [{k:q[k] for k in ['quiz_id','title','origin','created_at']} | {'count':len(q['questions']),'offering_id':offering_id}
                    for row in db.execute('SELECT snapshot FROM quizzes WHERE offering_id=? ORDER BY rowid DESC',(offering_id,))
                    for q in [json.loads(row[0])]]

    def _quiz(self, db, qid, offering_id=DEFAULT_OFFERING):
        row=db.execute('SELECT * FROM quizzes WHERE id=?',(qid,)).fetchone()
        if row is None or row['offering_id']!=offering_id: raise ScopeError('선택한 강좌의 문제를 찾을 수 없습니다.')
        quiz=json.loads(row['snapshot'])
        if signature(quiz)!=row['digest']: raise ValueError('문제 스냅샷 무결성 검사에 실패했습니다.')
        return quiz

    def start(self, sid, qid, offering_id=DEFAULT_OFFERING):
        self.require_course(sid,offering_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._quiz(db,qid,offering_id)
            # Reload/double-click resumes an unfinished attempt, not a fresh timer.
            for row in db.execute('SELECT * FROM attempts WHERE student_id=? AND quiz_id=? AND offering_id=? ORDER BY rowid DESC',(sid,qid,offering_id)):
                if not json.loads(row['state'])['done']: return self._view(db,row)
            aid=str(uuid.uuid4());state={'cursor':0,'revision':0,'done':False,'created_ms':self.clock(),'timing':None}
            db.execute('INSERT INTO attempts (id,student_id,quiz_id,state,offering_id) VALUES (?,?,?,?,?)',(aid,sid,qid,json.dumps(state),offering_id))
            return self._view(db,db.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone())

    def _attempt(self, db, sid, aid, offering_id=DEFAULT_OFFERING):
        row=db.execute('SELECT * FROM attempts WHERE id=? AND student_id=? AND offering_id=?',(aid,sid,offering_id)).fetchone()
        if row is None: raise ValueError('이 학습자의 풀이 기록을 찾을 수 없습니다.')
        return row

    def _view(self, db, row):
        s=json.loads(row['state']);q=self._quiz(db,row['quiz_id'],row['offering_id'])
        result={'offering_id':row['offering_id'],'attempt_id':row['id'],'quiz_id':row['quiz_id'],'title':q['title'],'origin':q['origin'],
                'revision':s['revision'],'done':s['done'],'number':s['cursor']+1,'total':len(q['questions'])}
        if not s['done']:
            item=q['questions'][s['cursor']]
            result['question']={k:item[k] for k in ['question_id','stem','options','concept_id','difficulty']}
            result['timing']=s['timing']
        else:
            records=[{**json.loads(r[0]),'offering_id':row['offering_id']} for r in db.execute('SELECT data FROM responses WHERE attempt_id=? ORDER BY recorded_ms',(row['id'],))]
            result['results']=records
            result['summary']={'correct':sum(x['correct'] for x in records),'total':len(records),
                'active_ms':sum(x['active_ms'] for x in records),'problem_elapsed_ms':sum(x['elapsed_ms'] for x in records),
                'quiz_elapsed_ms':s['finished_ms']-s['created_ms']}
        return result

    def view(self,sid,aid,offering_id=DEFAULT_OFFERING):
        self.require_course(sid,offering_id)
        with self.db() as db: return self._view(db,self._attempt(db,sid,aid,offering_id))

    def event(self,sid,aid,payload,offering_id=DEFAULT_OFFERING):
        self.require_course(sid,offering_id)
        kind=payload.get('kind');eid=payload.get('event_id')
        if kind not in ['shown','heartbeat','pause','resume','hint','submit']: raise ValueError('지원하지 않는 이벤트입니다.')
        if not isinstance(eid,str) or not 8 <= len(eid)<=80: raise ValueError('이벤트 ID가 필요합니다.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=self._attempt(db,sid,aid,offering_id)
            old=db.execute('SELECT * FROM events WHERE attempt_id=? AND event_id=?',(aid,eid)).fetchone()
            if old:
                if old['payload_digest']!=signature(payload): raise Conflict('같은 이벤트 ID에 다른 요청이 들어왔습니다.')
                return {**json.loads(old['response']),'offering_id':offering_id}
            s=json.loads(row['state']);quiz=self._quiz(db,row['quiz_id'],offering_id)
            if s['done'] or payload.get('revision')!=s['revision']: raise Conflict('풀이 상태가 바뀌었습니다. 화면을 새로 불러와 주세요.')
            item=quiz['questions'][s['cursor']]
            if payload.get('question_id')!=item['question_id']: raise Conflict('현재 문제가 아닙니다.')
            stamp=self.clock();t=s['timing']
            if t is None:
                if kind!='shown': raise Conflict('문제를 표시한 다음 풀어 주세요.')
                t={'started_ms':stamp,'last_ms':stamp,'active_ms':0,'inactive_ms':0,'unknown_ms':0,
                   'active':True,'hint_used':False,'clock_anomaly':False};s['timing']=t
            else:
                delta=stamp-t['last_ms']
                if delta<0:t['clock_anomaly']=True
                delta=max(0,delta)
                if t['active']:
                    t['active_ms']+=min(delta,15000)
                    t['unknown_ms']+=max(0,delta-15000)
                else:t['inactive_ms']+=delta
                t['last_ms']=max(stamp,t['last_ms'])
            if kind in ['shown','resume']:t['active']=True
            elif kind=='pause':t['active']=False
            elif kind=='hint':t['hint_used']=True
            feedback=None
            if kind=='submit':
                selected=payload.get('selected')
                if type(selected) is not int or not 0<=selected<4: raise ValueError('선택지 하나를 골라 주세요.')
                source=next(x for x in item['evidence']['sources'] if x['id']==item['source_id'])
                feedback={'offering_id':offering_id,'question_id':item['question_id'],'item_key':item['item_key'],'stem':item['stem'],
                    'selected':selected,'answer_index':item['answer_index'],'options':item['options'],
                    'correct':selected==item['answer_index'],'explanation':item['explanation'],
                    'concept_id':item['concept_id'],'concept_version':item['concept_version'],
                    'difficulty':item['difficulty'],'quiz_id':quiz['quiz_id'],'origin':quiz['origin'],
                    'corpus_version':item['evidence']['corpus_version'],'active_ms':t['active_ms'],
                    'elapsed_ms':max(0,stamp-t['started_ms']),'inactive_ms':t['inactive_ms'],
                    'unknown_ms':t['unknown_ms'],'hint_used':t['hint_used'],
                    'timing_valid':not t['clock_anomaly'] and t['unknown_ms']==0,
                    'submitted_ms':stamp,'source':{'file':source['source_file'],'slide':source['slide_number'],
                                                'quote':item['quote']}}
                db.execute('INSERT INTO responses (attempt_id,question_id,student_id,item_key,concept_id,recorded_ms,data,offering_id) VALUES (?,?,?,?,?,?,?,?)',(aid,item['question_id'],sid,
                    item['item_key'],item['concept_id'],stamp,json.dumps(feedback,ensure_ascii=False),offering_id))
                s['cursor']+=1;s['timing']=None
                if s['cursor']==len(quiz['questions']):s['done']=True;s['finished_ms']=stamp
            s['revision']+=1
            db.execute('UPDATE attempts SET state=? WHERE id=?',(json.dumps(s),aid))
            result=self._view(db,db.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone())
            if feedback:result['feedback']=feedback
            if kind=='hint':result['hint']=item['quote']
            db.execute('INSERT INTO events (attempt_id,event_id,payload_digest,response,offering_id) VALUES (?,?,?,?,?)',(aid,eid,signature(payload),json.dumps(result,ensure_ascii=False),offering_id))
            return result

    def analysis(self,sid,offering_id=DEFAULT_OFFERING):
        course=self.require_course(sid,offering_id)
        with self.db() as db:
            rows=[(r['student_id'],json.loads(r['data'])) for r in db.execute('SELECT * FROM responses WHERE offering_id=? ORDER BY recorded_ms,rowid',(offering_id,))]
        # First encounter of each item: repeated answers after feedback are not fresh evidence.
        first={}
        for student,r in rows:first.setdefault((student,r['item_key']),r)
        observed=[r for (student,_),r in first.items() if student==sid]
        concepts=[]
        for cid,label in course['concepts'].items():
            all_items=[r for r in observed if r['concept_id']==cid]
            items=[r for r in all_items if not r['hint_used']]
            n=len(items);wrong=sum(not r['correct'] for r in items)
            weights={'basic':1.25,'apply':1.0,'reason':0.75}
            weighted_error=sum(weights[r['difficulty']] for r in items if not r['correct'])/sum(weights[r['difficulty']] for r in items) if items else 0
            ratios=[]
            for r in items:
                if not r['timing_valid'] or r['active_ms']<1000:continue
                peers=[v['active_ms'] for (student,key),v in first.items() if key==r['item_key'] and student!=sid
                    and v['correct'] and not v['hint_used'] and v['timing_valid'] and v['active_ms']>=1000]
                if len(peers)>=5:ratios.append(r['active_ms']/median(peers))
            speed='시간 기준 부족' if len(ratios)<3 else ('상대적으로 느림' if median(ratios)>1.5 else '뚜렷한 지연 신호 없음')
            status='판단 보류' if n<3 else ('취약 가능성' if weighted_error>=.5 else '복습 권장' if weighted_error>=.25 else '현재 응답에서 안정적')
            if n>=3 and weighted_error<.25 and speed=='상대적으로 느림':status='정답은 안정적 · 속도 연습 후보'
            concepts.append({'concept_id':cid,'label':label,'status':status,'unique_questions':n,
                'correct':n-wrong,'wrong':wrong,'hint_excluded':len(all_items)-n,
                'weighted_error_ratio':round(weighted_error,3) if items else None,
                'median_active_seconds':round(median([r['active_ms']/1000 for r in items if r['timing_valid']]),1) if any(r['timing_valid'] for r in items) else None,
                'timing_valid_count':sum(r['timing_valid'] for r in items),'time_signal':speed,
                'time_comparisons':len(ratios),'median_time_ratio':round(median(ratios),2) if ratios else None,
                'difficulty_breakdown':{d:{'count':sum(r['difficulty']==d for r in items),
                    'wrong':sum(r['difficulty']==d and not r['correct'] for r in items)} for d in ['basic','apply','reason']}})
        return {'offering_id':offering_id,'course':{k:course[k] for k in ['subject_code','subject_name','semester','section']},'analysis_version':ANALYSIS_VERSION,'concepts':concepts,
            'total_responses':sum(student==sid for student,_ in rows),'unique_items':len(observed),
            'notice':'진단 확정값이 아닌 실험용 신호입니다. 개념별 서로 다른 첫 풀이 3개 미만은 판단 보류. 힌트 사용·동일 문제 재풀이는 신규 근거에서 제외합니다.',
            'timing_notice':'서버 수신 시각과 화면 상태로 추정한 활성시간입니다. 실제 집중시간을 보증하지 않습니다. 시간 비교는 같은 과목·학기·분반 내 같은 문항의 다른 학습자 5명 이상 및 해당 개념 3문항 이상일 때만 적용합니다.'}

    def shorts_handoff(self,sid,cid,offering_id=DEFAULT_OFFERING):
        course=self.require_course(sid,offering_id)
        if cid not in course['concepts']:raise ValueError('알 수 없는 개념입니다.')
        analysis=self.analysis(sid,offering_id);summary=next(x for x in analysis['concepts'] if x['concept_id']==cid)
        with self.db() as db:
            evidence=[];seen=set()
            for row in db.execute('SELECT DISTINCT quiz_id FROM attempts WHERE student_id=? AND offering_id=?',(sid,offering_id)):
                quiz=self._quiz(db,row['quiz_id'],offering_id)
                for q in quiz['questions']:
                    if q['concept_id']==cid:
                        for source in q['evidence']['sources']:
                            key=(q['evidence']['corpus_version'],source['id'])
                            if key not in seen:
                                seen.add(key);evidence.append({'corpus_version':key[0],'source':source})
        return {'schema_version':2,'offering_id':offering_id,'course':analysis['course'],'type':'learning_content_request','created_at':now(),
            'concept_id':cid,'concept_label':course['concepts'][cid],'analysis':summary,
            'analysis_version':ANALYSIS_VERSION,'evidence_snapshots':evidence,
            'target':'short_video','status':'prepared_only','rendering_provider':'heygen_planned',
            'instruction':'학생을 단정적으로 평가하지 말고 개념 설명과 예시를 구성. 최신 자료로 출처 재검증 후 대본 생성·영상 제작 단계에 전달.',
            'video_generated':False}
