"""Course offering boundary: subject + semester + section, independent of concept IDs."""
import json
from contextlib import closing
import re
import sqlite3
import unicodedata
import uuid

from video_extraction.shared.common import now
from . import CONCEPTS

DEFAULT_OFFERING = 'legacy-stack'


class ScopeError(ValueError): pass


def catalog(value):
    if not isinstance(value,dict) or not 1 <= len(value) <= 100:
        raise ValueError('개념 목록은 1~100개의 ID와 이름으로 입력하세요.')
    for key,label in value.items():
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}',key):
            raise ValueError('개념 ID는 영문 소문자로 시작하고 숫자·점·밑줄·하이픈을 사용할 수 있습니다.')
        if not isinstance(label,str) or not 1 <= len(label.strip()) <= 100:raise ValueError('개념 이름을 확인하세요.')
    return {key:label.strip() for key,label in value.items()}


def migrate_courses(db,path):
    version=db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    if version=='2':return
    if version!='1':raise ValueError('지원하지 않는 학습 DB 버전입니다.')
    # Preserve the pre-migration DB and immutable JSON snapshots, including unfinished attempts.
    backup=path.with_name(path.name+'.pre-course-v2.sqlite3')
    if not backup.exists():
        with closing(sqlite3.connect(backup)) as dest:db.backup(dest)
    db.execute('BEGIN IMMEDIATE')
    db.execute('''CREATE TABLE offerings (id TEXT PRIMARY KEY, subject_code TEXT NOT NULL,
        subject_name TEXT NOT NULL, semester TEXT NOT NULL, section TEXT NOT NULL,
        concepts TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(subject_code,semester,section))''')
    db.execute('INSERT INTO offerings VALUES (?,?,?,?,?,?,?)',(DEFAULT_OFFERING,'LEGACY-DS',
        '자료구조 (기존 테스트)','학기 미지정','기본',json.dumps(CONCEPTS,ensure_ascii=False),now()))
    db.execute('''CREATE TABLE enrollments (student_id TEXT NOT NULL, offering_id TEXT NOT NULL,
        PRIMARY KEY(student_id,offering_id))''')
    db.execute('INSERT INTO enrollments SELECT id,? FROM students',(DEFAULT_OFFERING,))
    for table in ['quizzes','attempts','responses','events']:
        db.execute(f"ALTER TABLE {table} ADD COLUMN offering_id TEXT NOT NULL DEFAULT 'legacy-stack'")
        db.execute(f'CREATE INDEX {table}_offering ON {table}(offering_id)')
    db.execute('CREATE INDEX response_course_student ON responses(offering_id,student_id,recorded_ms)')
    db.execute('''CREATE TABLE materials (id TEXT PRIMARY KEY, offering_id TEXT NOT NULL,
        corpus_version TEXT NOT NULL, relative_path TEXT NOT NULL, chunk_count INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        UNIQUE(offering_id,corpus_version))''')
    db.execute('CREATE UNIQUE INDEX one_active_corpus ON materials(offering_id) WHERE active=1')
    db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('course_migration',?)",(json.dumps({'at':now(),
        'default_offering':DEFAULT_OFFERING,'note':'Original quiz/response/event JSON snapshots unchanged'}),))


class CourseStore:
    def course(self,oid):
        with self.db() as db:
            row=db.execute('SELECT * FROM offerings WHERE id=?',(oid,)).fetchone()
            if row is None:raise ScopeError('강좌를 찾을 수 없습니다.')
            result=dict(row);result['concepts']=json.loads(result['concepts'])
            return result

    def courses(self,sid):
        self.profile(sid)
        with self.db() as db:
            return [dict(row) for row in db.execute('''SELECT o.id,o.subject_code,o.subject_name,o.semester,o.section,
                EXISTS(SELECT 1 FROM enrollments e WHERE e.student_id=? AND e.offering_id=o.id) AS enrolled
                FROM offerings o ORDER BY created_at,id''',(sid,))]

    def create_course(self,subject_code,subject_name,semester,section,concepts=None):
        values=[]
        for value in [subject_code,subject_name,semester,section]:
            if not isinstance(value,str) or not 1<=len(value.strip())<=80:raise ValueError('과목 코드·이름·학기·분반을 모두 입력하세요.')
            values.append(unicodedata.normalize('NFC',value.strip()))
        values[0]=values[0].upper()
        concepts=catalog(CONCEPTS if concepts is None else concepts)
        oid=str(uuid.uuid4())
        try:
            with self.db() as db:db.execute('INSERT INTO offerings VALUES (?,?,?,?,?,?,?)',
                (oid,*values,json.dumps(concepts,ensure_ascii=False),now()))
        except sqlite3.IntegrityError:raise ValueError('동일한 과목 코드·학기·분반 강좌가 이미 있습니다.') from None
        return self.course(oid)

    def enroll(self,sid,oid):
        self.profile(sid);self.course(oid)
        with self.db() as db:db.execute('INSERT OR IGNORE INTO enrollments VALUES (?,?)',(sid,oid))

    def require_course(self,sid,oid):
        if not oid:raise ScopeError('과목·학기·분반을 먼저 선택하세요.')
        course=self.course(oid)
        with self.db() as db:
            if db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND offering_id=?',(sid,oid)).fetchone() is None:
                raise ScopeError('선택한 강좌에 등록된 테스트 학습자가 아닙니다.')
        return course

    def materials(self,oid):
        self.course(oid)
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM materials WHERE offering_id=? ORDER BY created_at DESC',(oid,))]

    def register_material(self,oid,version,relative_path,count):
        self.course(oid)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE materials SET active=0 WHERE offering_id=?',(oid,))
            db.execute('''INSERT INTO materials VALUES (?,?,?,?,?,1,?)
                ON CONFLICT(offering_id,corpus_version) DO UPDATE SET active=1''',
                (str(uuid.uuid4()),oid,version,relative_path,count,now()))
        return next(m for m in self.materials(oid) if m['active'])
