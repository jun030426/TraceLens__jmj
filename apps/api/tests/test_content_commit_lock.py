"""Real PostgreSQL FK lock regression; explicit isolated localhost database only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.evaluation import lock_course_for_artifact_commit
from lerny.models import Course


@pytest.fixture
def lock_database():
    from sqlalchemy.engine import make_url
    if not settings().database_url:
        pytest.skip('Requires isolated local PostgreSQL test runner')
    url=make_url(settings().database_url)
    assert url.host in {'127.0.0.1','localhost','::1'} and url.database=='lerny_test'
    engine=create_engine(url)
    schema='lock_test_'+uuid4().hex
    with engine.begin() as db:
        db.execute(text(f'CREATE SCHEMA {schema}'))
        db.execute(text(f'''CREATE TABLE {schema}.courses (id varchar PRIMARY KEY, term_id varchar,
            title varchar, lead_teacher_id varchar, teaching_language varchar, revision int,
            access_epoch int, created_at timestamptz DEFAULT now())'''))
        db.execute(text(f"INSERT INTO {schema}.courses (id,access_epoch,revision) VALUES ('course',0,1)"))
        db.execute(text(f'CREATE TABLE {schema}.artifacts (id int PRIMARY KEY, course_id varchar REFERENCES {schema}.courses(id))'))
    try:yield engine,schema
    finally:
        with engine.begin() as db:db.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


def configure(db,schema,timeout='5s'):
    db.execute(text(f'SET LOCAL search_path TO {schema}'))
    db.execute(text(f"SET LOCAL lock_timeout='{timeout}'"))
    db.execute(text("SET LOCAL statement_timeout='8s'"))
    db.execute(text("SET LOCAL deadlock_timeout='100ms'"))


@pytest.mark.parametrize('legacy',[True,False])
def test_parallel_artifact_fk_inserts(lock_database,legacy):
    engine,schema=lock_database
    barrier=Barrier(2)
    def save(number):
        with Session(engine) as db:
            configure(db,schema)
            db.execute(text('INSERT INTO artifacts VALUES (:id, :course)'),{'id':number,'course':'course'})
            barrier.wait(timeout=5)
            try:
                if legacy:db.scalar(select(Course).where(Course.id=='course').with_for_update())
                else:assert lock_course_for_artifact_commit(db,'course').access_epoch==0
                db.commit()
                return 'committed'
            except OperationalError as exc:
                db.rollback()
                return exc.orig.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save,[1,2]))
    assert sorted(results)==(['40P01','committed'] if legacy else ['committed','committed'])


def test_epoch_changes_still_wait_for_artifact_commit(lock_database):
    engine,schema=lock_database
    with Session(engine) as first,Session(engine) as second:
        configure(first,schema)
        first.execute(text("INSERT INTO artifacts VALUES (1,'course')"))
        locked=lock_course_for_artifact_commit(first,'course')
        assert locked.access_epoch==0
        configure(second,schema,'100ms')
        with pytest.raises(OperationalError) as caught:
            second.execute(text("UPDATE courses SET access_epoch=1 WHERE id='course'"))
        assert caught.value.orig.sqlstate=='55P03'
        second.rollback();first.commit()
        configure(second,schema)
        second.execute(text("UPDATE courses SET access_epoch=1 WHERE id='course'"));second.commit()
        configure(first,schema)
        assert lock_course_for_artifact_commit(first,'course').access_epoch==1
