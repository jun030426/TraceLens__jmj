"""Professor-only reads on disposable PostgreSQL. No AI, execution or network calls."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event, func, select

from lerny import professor_analytics as metrics
from lerny.models import (Attempt, ChatMessage, Concept, CourseStaff, Enrollment, Job, LearningSession,
    MaterialVersion, PracticeAttempt, PracticeExercise, PracticeSession, Question, Section, User, now)
from test_identity_courses import login
from test_learning import seed

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Professor analysis must never call a provider")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


async def setup(client, session):
    course, section, material = await seed(client, session)
    student = session.scalar(select(User).where(User.login_id == "student1"))
    question = session.scalar(select(Question).where(Question.course_id == course["id"]))
    concept = session.get(Concept, question.concept_id)
    concept.name = "스택"
    version = session.get(MaterialVersion, material.active_version_id)
    version.concept_ids = [concept.id]
    session.commit()
    await login(client, "teacher1")
    return section["id"], student.id, question, material, version


def theory(session, section_id, student_id, template, correct, *, days=0, independent=True, status="graded", review=False, moment=None):
    moment = moment or now() - timedelta(days=days)
    day = metrics.local_day(moment)
    learning = session.scalar(select(LearningSession).where(LearningSession.student_id == student_id,
        LearningSession.section_id == section_id, LearningSession.day == day))
    if not learning:
        learning = LearningSession(student_id=student_id, section_id=section_id, day=day, question_ids=[])
        session.add(learning); session.flush()
    question = Question(course_id=template.course_id, concept_id=template.concept_id, generation_id=template.generation_id, kind="mcq",
        prompt="Audit source question", options=["정답","오답","다른 답","모름"],
        solution={"answer_index":0,"explanation":"source","criteria":[],"review":review}, sources=template.sources)
    session.add(question); session.flush()
    learning.question_ids = [*learning.question_ids, question.id]
    attempt = Attempt(student_id=student_id, section_id=section_id, learning_session_id=learning.id,
        question_id=question.id, concept_id=question.concept_id, answer="0" if correct else "1",
        correct=correct, status=status, independent=independent, created_at=moment)
    session.add(attempt); session.flush()
    return attempt


def practice(session, section_id, student_id, question, version, correct, *, moment=None, independent=True):
    exercise = session.scalar(select(PracticeExercise).where(PracticeExercise.version_id == version.id))
    if not exercise:
        exercise = PracticeExercise(course_id=question.course_id, version_id=version.id, concept_id=question.concept_id, generation_id=question.generation_id,
            source_key="audit", position=1, kind="full", language="python", title="고정 실습",
            prompt="test", template="", reference="", sources=question.sources, status="ready")
        session.add(exercise); session.flush()
    moment = moment or now()
    day = metrics.local_day(moment)
    plan = session.scalar(select(PracticeSession).where(PracticeSession.student_id == student_id,
        PracticeSession.section_id == section_id, PracticeSession.day == day))
    if not plan:
        plan = PracticeSession(student_id=student_id, section_id=section_id, day=day, week=1, exercise_ids=[exercise.id])
        session.add(plan); session.flush()
    attempt = PracticeAttempt(student_id=student_id, section_id=section_id, exercise_id=exercise.id,
        practice_session_id=plan.id, source=f"# never executed {moment.isoformat()}", correct=correct,
        independent=independent, status="graded", created_at=moment, feedback={"message":"test","passed":int(correct),"total":1})
    session.add(attempt); session.flush()
    return attempt


def route(section, student=None):
    return f"/api/v1/sections/{section}" + (f"/students/{student}" if student else "") + "/insights"


async def test_domains_recent_evidence_trend_review_and_read_only(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section, student, q, _, version = await setup(client, session)
        for i, correct in enumerate([False,False,False,True,True,True,True,True,True,True]):
            theory(session,section,student,q,correct,days=i,review=i<2)
        theory(session,section,student,q,True,independent=False)
        theory(session,section,student,q,None,status="held")
        practice(session,section,student,q,version,True)
        session.commit()
        before = session.scalar(select(func.count()).select_from(Job))
        response = await client.get(route(section,student))
        assert response.status_code == 200, response.text
        result = response.json()
        assert "no-store" in response.headers["cache-control"]
        assert result["theory"]["accuracy"] == 70
        assert result["theory"]["assisted"] == result["theory"]["pending"] == 1
        assert result["practice_summary"]["accuracy"] == 100
        item = result["concepts"][0]
        assert item["accuracy"] == 70  # compatibility alias is theory-only
        assert item["learning"]["weakness"] == 60 and item["learning"]["trend_points"] == -60
        assert item["learning"]["state"] == "review" and len(item["learning"]["evidence"]) == 5
        assert item["learning"]["review"]["wrong"] == 2
        overview = (await client.get(route(section))).json()
        roster = next(s for s in overview["students"] if s["id"] == student)
        signal = roster["concept_signals"][0]
        assert signal["weakness"] == 60 and signal["state"] == "review"
        assert signal["sample"] == 5 and signal["correct"] == 2
        assert signal["id"] == item["id"] and signal["name"] == item["name"]
        assert set(signal) == {"id", "name", "state", "sample", "correct", "success_days", "weakness", "trend_points"}
        assert session.scalar(select(func.count()).select_from(Job)) == before


async def test_class_weights_actual_attempts_and_counts_each_student_once(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section, student, q, _, _ = await setup(client,session)
        other = session.scalar(select(User).where(User.login_id=="student2"))
        session.add(Enrollment(student_id=other.id,section_id=section,course_id=q.course_id,status="active"))
        for i in range(5): theory(session,section,student,q,False,days=i)
        theory(session,section,other.id,q,True)
        # Historical enrollment must not duplicate the roster or denominator.
        session.add(Enrollment(student_id=student,section_id=section,course_id=q.course_id,status="withdrawn"))
        session.commit()
        result = (await client.get(route(section))).json()
        assert result["student_count"] == 2 and result["theory"]["accuracy"] == 16.7
        item = result["concepts"][0]
        assert item["review_students"] == item["insufficient_students"] == 1
        assert item["mastered_students"] == 0 and "learning" not in item
        assert next(s for s in result["students"] if s["id"] == other.id)["insufficient_concepts"] == 1
        assert next(s for s in result["students"] if s["id"] == student)["concept_signals"][0]["weakness"] == 100
        sparse = next(s for s in result["students"] if s["id"] == other.id)["concept_signals"][0]
        assert sparse["weakness"] is None and sparse["sample"] == 1


async def test_no_data_small_samples_and_two_success_dates(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section, student, q, _, version = await setup(client,session)
        result = (await client.get(route(section,student))).json()
        assert result["concepts"] == [] and result["theory"]["accuracy"] is None
        roster = (await client.get(route(section))).json()["students"]
        assert next(s for s in roster if s["id"] == student)["concept_signals"] == []
        unobserved = (await client.get(route(section))).json()["concepts"]
        assert any(c["id"] == q.concept_id for c in unobserved)
        assert all(c["theory"]["accuracy"] is None and c["review_students"] == 0 for c in unobserved)
        practice(session,section,student,q,version,False)
        session.commit()
        item = (await client.get(route(section,student))).json()["concepts"][0]
        assert item["learning"]["state"] == "no_data" and item["learning"]["weakness"] is None
        theory(session,section,student,q,False)
        session.commit()
        item = (await client.get(route(section,student))).json()["concepts"][0]
        assert item["learning"]["state"] == "insufficient" and item["learning"]["weakness"] is None
        for _ in range(4): theory(session,section,student,q,True)
        session.commit()
        item = (await client.get(route(section,student))).json()["concepts"][0]
        assert item["learning"]["state"] == "learning"
        theory(session,section,student,q,True,days=1)
        session.commit()
        # The earlier date is sixth and therefore must not establish recent-five mastery.
        item = (await client.get(route(section,student))).json()["concepts"][0]
        assert item["learning"]["success_days"] == 1


async def test_chat_topics_are_private_bounded_and_conservative(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section, student, q, material, version = await setup(client,session)
        citation={"version_id":version.id,"material_id":material.id,"excerpt":"PRIVATE_CITATION"}
        for question,citations,days in [("스택 PRIVATE_NAME",[],0),("PRIVATE_INFER",[citation],0),
                                        ("PRIVATE_UNKNOWN",[],0),("스택 PRIVATE_EXPIRED",[],91)]:
            session.add(ChatMessage(student_id=student,section_id=section,thread_id="audit",question=question,
                access_epoch=1,created_at=now()-timedelta(days=days),
                answer={"answer":"PRIVATE_ANSWER","citations":citations}))
        session.commit()
        query=f"?date_from={(metrics.local_day(now())-timedelta(days=120)).isoformat()}"
        result = (await client.get(route(section,student)+query)).json()
        assert "PRIVATE_" not in json.dumps(result)
        assert result["chat"]["count"] == 3 and result["chat"]["unclassified"] == 1
        topic=result["chat"]["topics"][0]
        assert topic["name_matches"] == topic["source_inferences"] == 1
        assert result["concepts"][0]["learning"]["state"] == "no_data"
        # Revoked source metadata must no longer classify the otherwise anonymous question.
        material.visibility="private";session.commit()
        result=(await client.get(route(section,student)+query)).json()
        assert result["chat"]["unclassified"] == 2


async def test_authorization_dates_foreign_concept_and_membership(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section, student, q, _, _ = await setup(client,session)
        assert (await client.get(route(section)+"?date_from=2026-11-12&date_to=2026-11-11")).status_code == 422
        assert (await client.get(route(section)+"?date_from=2024-01-01&date_to=2026-01-01")).status_code == 422
        assert (await client.get(route(section,student)+"?concept_id=foreign")).status_code == 404
        assert (await client.get(route(section,"non-member"))).status_code == 404
        await login(client,"student1")
        assert (await client.get(route(section))).status_code == 404
        assert (await client.get(route(section,student))).status_code == 404
        await login(client,"teacher2")
        assert (await client.get(route(section))).status_code == 404
        teacher=session.scalar(select(User).where(User.login_id=="teacher2"))
        staff=CourseStaff(course_id=q.course_id,teacher_id=teacher.id,can_edit=True,can_analyze=False)
        session.add(staff);session.commit()
        assert (await client.get(route(section,student))).status_code == 403
        staff.can_analyze=True;session.commit()
        assert (await client.get(route(section,student))).status_code == 200


async def test_korea_date_boundary_practice_pagination_and_constant_queries(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        section,student,q,_,version=await setup(client,session)
        today=metrics.local_day(now())
        midnight=datetime.combine(today,datetime.min.time(),metrics.KOREA)
        theory(session,section,student,q,True,moment=midnight)
        theory(session,section,student,q,False,moment=midnight-timedelta(seconds=1))
        for i in range(23): practice(session,section,student,q,version,bool(i%2),moment=midnight+timedelta(minutes=i))
        session.commit();session.expire_all()
        calls=[]
        def count(*args): calls.append(1)
        event.listen(session.bind,"before_cursor_execute",count)
        try:
            query=f"?date_from={today}&date_to={today}"
            response=await client.get(route(section,student)+query)
            result=response.json()
            assert response.status_code==200,response.text
            assert result["theory"]["independent"]==1 and result["theory"]["accuracy"]==100
            assert result["practice_page"]["total"]==23 and len(result["practice"])==10
            assert len(calls)<20  # no per-attempt source/feedback/exercise query
            second=(await client.get(route(section,student)+query+"&practice_offset=10")).json()
            assert not ({a["id"] for a in result["practice"]}&{a["id"] for a in second["practice"]})
            assert all(a["source"].startswith("# never executed") for a in second["practice"])
        finally:
            event.remove(session.bind,"before_cursor_execute",count)
