"""Persistent chat turns scoped to one student and one course offering."""
import json
import uuid
from video_extraction.shared.common import now
from .courses import ScopeError


def init_chat(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS chat_turns (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        student_id TEXT NOT NULL, offering_id TEXT NOT NULL, request_id TEXT NOT NULL,
        question TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','complete','failed')),
        created_at TEXT NOT NULL, finished_at TEXT, result TEXT, context TEXT, error TEXT,
        UNIQUE(student_id,offering_id,request_id));
    CREATE INDEX IF NOT EXISTS chat_scope ON chat_turns(student_id,offering_id,seq);
    CREATE UNIQUE INDEX IF NOT EXISTS chat_one_pending ON chat_turns(student_id,offering_id) WHERE state='pending';
    INSERT OR IGNORE INTO meta VALUES ('chat_schema_version','1');
    ''')


def public_turn(row):
    return {k:row[k] for k in ['seq','id','question','state','created_at','finished_at','error']} | {
        'offering_id':row['offering_id'], 'result':json.loads(row['result']) if row['result'] else None}


class ChatStore:
    def chat_turn(self,sid,oid,tid):
        self.require_course(sid,oid)
        with self.db() as db:
            row=db.execute('SELECT * FROM chat_turns WHERE id=? AND student_id=? AND offering_id=?',(tid,sid,oid)).fetchone()
            if row is None:raise ScopeError('현재 학생·강좌의 대화를 찾을 수 없습니다.')
            return public_turn(row)

    def chat_history(self,sid,oid,before=None):
        self.require_course(sid,oid)
        if before is not None and (type(before) is not int or before<1):raise ValueError('대화 페이지 번호가 올바르지 않습니다.')
        with self.db() as db:
            rows=db.execute('SELECT * FROM chat_turns WHERE student_id=? AND offering_id=? AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT 31',
                (sid,oid,before,before)).fetchall()
        return {'turns':[public_turn(r) for r in reversed(rows[:30])],
                'next_before':rows[29]['seq'] if len(rows)>30 else None,'offering_id':oid}

    def chat_context_rows(self,sid,oid):
        self.require_course(sid,oid)
        with self.db() as db:
            rows=db.execute("SELECT * FROM chat_turns WHERE student_id=? AND offering_id=? AND state='complete' ORDER BY seq DESC LIMIT 200",(sid,oid)).fetchall()
        return [public_turn(r) for r in reversed(rows)]

    def chat_existing(self,sid,oid,request_id,question):
        self.require_course(sid,oid)
        try:uuid.UUID(request_id)
        except (ValueError,TypeError,AttributeError):raise ValueError('대화 요청 ID가 올바르지 않습니다.') from None
        if not isinstance(question,str) or not question.strip() or len(question)>2000:raise ValueError('질문은 1~2000자로 입력하세요.')
        with self.db() as db:
            row=db.execute('SELECT * FROM chat_turns WHERE student_id=? AND offering_id=? AND request_id=?',(sid,oid,request_id)).fetchone()
            if row:
                if row['question']!=question:
                    from .store import Conflict
                    raise Conflict('같은 요청 ID에 다른 질문을 보낼 수 없습니다.')
                return public_turn(row)

    def chat_begin(self,sid,oid,request_id,question):
        from .store import Conflict
        existing=self.chat_existing(sid,oid,request_id,question)
        if existing:return existing,False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Recheck inside transaction for retries from concurrent HTTP requests.
            old=db.execute('SELECT * FROM chat_turns WHERE student_id=? AND offering_id=? AND request_id=?',(sid,oid,request_id)).fetchone()
            if old:
                if old['question']!=question:raise Conflict('같은 요청 ID의 질문이 다릅니다.')
                return public_turn(old),False
            if db.execute("SELECT 1 FROM chat_turns WHERE student_id=? AND offering_id=? AND state='pending'",(sid,oid)).fetchone():raise Conflict('이 강좌의 이전 답변을 생성 중입니다.')
            tid=str(uuid.uuid4())
            db.execute('INSERT INTO chat_turns(id,student_id,offering_id,request_id,question,state,created_at) VALUES (?,?,?,?,?,?,?)',
                (tid,sid,oid,request_id,question,'pending',now()))
        return self.chat_turn(sid,oid,tid),True

    def chat_finish(self,sid,oid,tid,result,context):
        self.require_course(sid,oid)
        if result.get('offering_id')!=oid or any(s.get('offering_id')!=oid for s in result.get('sources',[])):
            raise ScopeError('답변 근거가 현재 강좌와 다릅니다.')
        with self.db() as db:
            changed=db.execute("UPDATE chat_turns SET state='complete',result=?,context=?,finished_at=? WHERE id=? AND student_id=? AND offering_id=? AND state='pending'",
                (json.dumps(result,ensure_ascii=False),json.dumps(context,ensure_ascii=False),now(),tid,sid,oid)).rowcount
            if changed!=1:raise ScopeError('저장할 대화 상태를 찾을 수 없습니다.')

    def chat_fail(self,sid,oid,tid,message):
        self.require_course(sid,oid)
        with self.db() as db:
            db.execute("UPDATE chat_turns SET state='failed',error=?,finished_at=? WHERE id=? AND student_id=? AND offering_id=? AND state='pending'",
                (message[:300],now(),tid,sid,oid))

    def interrupt_pending_chats(self):
        # Called only by App startup after binding its port, not by ordinary Store readers.
        with self.db() as db:
            return db.execute("UPDATE chat_turns SET state='failed',error=?,finished_at=? WHERE state='pending'",
                ('서버 재시작으로 답변 생성이 중단되었습니다. 질문을 다시 보내 주세요.',now())).rowcount
