import httpx
import pytest
from sqlalchemy import select
from lerny import worker
from lerny.automatic import concepts_job, sync_progress
from lerny.models import Job, Material, MaterialVersion, Section
from test_identity_courses import login, setup_course
from test_materials import upload, files_root
pytestmark=pytest.mark.asyncio

async def test_upload_pipeline_and_manual_override(app_db,files_root,monkeypatch):
    app,session=app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        await login(c,"teacher1");course,section=await setup_course(c)
        created=(await upload(c,course["id"])).json()
        worker.extract_job(session,session.get(Job,created["processing_job_id"]));session.flush()
        job=session.scalar(select(Job).where(Job.kind=="auto_concepts"))
        assert job
        monkeypatch.setattr(worker,"model_json",lambda *args:{"concepts":[{"name":"큐","quote":"큐는 선입선출 자료구조입니다."}]})
        result=concepts_job(session,job);session.flush()
        sec=session.get(Section,section["id"])
        assert set(sec.progress)==set(result["concept_ids"])
        assert session.scalar(select(Job).where(Job.kind=="questions")).payload["source_version_id"]==created["version_id"]
        sec.progress_mode="manual";sec.progress=[];sync_progress(session,course["id"])
        assert sec.progress==[]
        sec.progress_mode="auto";sync_progress(session,course["id"])
        assert sec.progress
        session.get(Material,created["material_id"]).visibility="private";session.flush();sync_progress(session,course["id"])
        assert sec.progress==[]

async def test_private_sources_never_enqueue(app_db,files_root):
    app,session=app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        await login(c,"teacher1");course,_=await setup_course(c)
        result=(await upload(c,course["id"],"private")).json()
        worker.extract_job(session,session.get(Job,result["processing_job_id"]));session.flush()
        assert session.scalar(select(Job).where(Job.kind=="auto_concepts")) is None

async def test_exam_plan_permissions_and_weeks(app_db):
    app,_=app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        await login(c,"teacher1");course,section=await setup_course(c)
        path=f"/api/v1/courses/{course['id']}/exam-plans"
        assert (await c.post(path,json={"title":"중간고사","start_week":8,"end_week":1})).status_code==422
        plan=(await c.post(path,json={"title":"중간고사","start_week":1,"end_week":8})).json()
        code=(await c.post(f"/api/v1/sections/{section['id']}/join-code",json={})).json()["join_code"]
        await login(c,"student1");await c.post("/api/v1/enrollments",json={"join_code":code})
        assert (await c.get(path)).json()["items"]==[]
        assert (await c.get(f"/api/v1/exam-plans/{plan['id']}/practice")).status_code==404
        assert (await c.post(path,json={"title":"잘못된 요청","start_week":1,"end_week":8})).status_code==404


async def test_exam_questions_scope_and_answer_disclosure(app_db,files_root):
    from lerny.models import Chunk, Question, ExamPlan
    app,session=app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        await login(c,"teacher1");course,section=await setup_course(c)
        result=(await upload(c,course["id"])).json()
        worker.extract_job(session,session.get(Job,result["processing_job_id"]));session.flush()
        chunk=session.scalar(select(Chunk).where(Chunk.version_id==result["version_id"]))
        q=Question(course_id=course["id"],concept_id=None,kind="mcq",prompt="큐의 순서는?",options=["FIFO","LIFO","랜덤","없음"],solution={"answer_index":0,"explanation":"선입선출입니다.","criteria":[]},sources=[{"chunk_id":chunk.id,"quote":chunk.content}])
        from lerny.models import Concept
        concept=Concept(course_id=course["id"],name="큐");session.add(concept);session.flush();q.concept_id=concept.id;session.add(q)
        plan=ExamPlan(course_id=course["id"],title="중간고사",start_week=1,end_week=1,published=True);session.add(plan);session.commit()
        code=(await c.post(f"/api/v1/sections/{section['id']}/join-code",json={})).json()["join_code"]
        await login(c,"student1");await c.post("/api/v1/enrollments",json={"join_code":code})
        data=(await c.get(f"/api/v1/exam-plans/{plan.id}/practice")).json()
        assert len(data["questions"])==1 and "solution" not in data["questions"][0]
        assert (await c.post(f"/api/v1/exam-plans/{plan.id}/questions/{q.id}/review",json={"answer":"0"})).json()["correct"] is True
        session.get(Material,result["material_id"]).week=2;session.commit()
        assert (await c.get(f"/api/v1/exam-plans/{plan.id}/practice")).json()["questions"]==[]
        assert (await c.post(f"/api/v1/exam-plans/{plan.id}/questions/{q.id}/review",json={"answer":"0"})).status_code==404


async def test_weekly_schedule_and_manual_boundary(app_db, files_root):
    from datetime import date, timedelta
    from lerny.models import Concept
    from lerny.automatic import calendar_week
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await login(c, "teacher1")
        course, section = await setup_course(c)
        material = (await upload(c, course["id"])).json()
        version = session.get(MaterialVersion, material["version_id"])
        first = Concept(course_id=course["id"], name="주차 개념")
        session.add(first); session.flush()
        version.status = "ready"; version.concept_ids = [first.id]
        session.get(Material, material["material_id"]).active_version_id = version.id
        sec = session.get(Section, section["id"])
        sec.week_schedule = [{"week":1,"date":(date.today()+timedelta(days=2)).isoformat()}]
        session.commit()
        assert calendar_week(session, sec, date.today()) == 0
        assert calendar_week(session, sec, date.today()+timedelta(days=2)) == 1
        sync_progress(session, course["id"])
        assert sec.progress == []
        path = f"/api/v1/sections/{sec.id}/weekly-progress"
        current = (await c.get(path)).json()
        result = await c.put(path, headers={"If-Match":str(current["revision"])}, json={"mode":"manual","week":1,"concept_ids":[first.id]})
        assert result.status_code == 200, result.text
        session.refresh(sec)
        assert sec.progress == [first.id] and sec.progress_week == 1
        sync_progress(session, course["id"])
        assert sec.progress == [first.id]
        stale = await c.put(path, headers={"If-Match":str(current["revision"])}, json={"mode":"auto","week":0})
        assert stale.status_code == 409
        current = (await c.get(path)).json()
        invalid = await c.put(path, headers={"If-Match":str(current["revision"])}, json={"mode":"auto","week":0,"schedule":[{"week":1,"date":"invalid"}]})
        assert invalid.status_code == 422
        current = (await c.get(path)).json()
        result = await c.put(path, headers={"If-Match":str(current["revision"])}, json={"mode":"auto","week":0})
        assert result.status_code == 200, result.text
        session.refresh(sec)
        assert sec.progress == [] and sec.progress_week is None
        await login(c, "student1")
        assert (await c.get(path)).status_code == 404

async def test_semester_is_sixteen_weeks(app_db):
    from datetime import date
    from types import SimpleNamespace
    from lerny.automatic import section_schedule, calendar_week
    from lerny.models import Term, Course
    class Lookup:
        def get(self, model, key):
            return SimpleNamespace(term_id="term") if model is Course else SimpleNamespace(starts_on=date(2026,9,1),ends_on=date(2099,12,31))
    session = Lookup()
    section = SimpleNamespace(course_id="course",week_schedule=[])
    rows = section_schedule(session, section)
    assert len(rows) == 16
    assert rows[0] == {"week":1,"date":"2026-09-01"}
    assert rows[-1] == {"week":16,"date":"2026-12-15"}
    assert calendar_week(session, section, date(2026,10,11)) == 6
    assert calendar_week(session, section, date(2027,1,1)) == 16

