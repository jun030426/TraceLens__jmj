"""Student/professor parity on disposable PostgreSQL; no AI or code execution."""
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import func, select
from lerny.models import Chunk, Enrollment, Job, Section, User, now
from lerny.professor_analytics import local_day, window
from test_identity_courses import login
from test_professor_insights import setup, theory, practice, route

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs): raise AssertionError("Read-only insights must not call a provider")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)

@pytest.mark.parametrize("values,same_day,state,score", [
    ([False, False], False, "insufficient", None),
    ([True]*5, True, "learning", 0),
    ([True]*4+[False], False, "mastered", 20),
    ([False]*4+[True], False, "review", 80),
])
async def test_same_evidence_and_state_for_both_roles(app_db, values, same_day, state, score):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        section, student, q, _, _ = await setup(client, session)
        for i, value in enumerate(values): theory(session,section,student,q,value,days=0 if same_day else i)
        theory(session,section,student,q,True,independent=False)
        theory(session,section,student,q,None,status="held")
        session.commit()
        prof = (await client.get(route(section,student))).json()["concepts"][0]["learning"]
        await login(client,"student1")
        response = await client.get(f"/api/v1/sections/{section}/my-learning")
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers["cache-control"]
        own = response.json()["items"][0]
        assert own["learning"] == {k: prof[k] for k in own["learning"]}
        assert own["learning"]["state"] == state and own["learning"]["weakness"] == score
        assert own["mastered"] == (state == "mastered")

async def test_section_and_kst_window_exclude_old_evidence(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        section, student, q, _, _ = await setup(client,session)
        old = Section(course_id=q.course_id,title="이전 분반")
        session.add(old); session.flush()
        session.add(Enrollment(student_id=student,course_id=q.course_id,section_id=old.id,status="withdrawn"))
        for i in range(5): theory(session,old.id,student,q,True,days=i)
        for i in range(5): theory(session,section,student,q,True,days=40+i)
        theory(session,section,student,q,False)
        first,last,start,end = window()
        boundary = theory(session,section,student,q,True,moment=start)
        outside = theory(session,section,student,q,True,moment=start-timedelta(microseconds=1))
        theory(session,section,student,q,True,moment=end)
        session.commit()
        before=session.scalar(select(func.count()).select_from(Job))
        for extra,expected in [("",2),(f"?date_from={(local_day(now())-timedelta(days=90)).isoformat()}",5)]:
            await login(client,"teacher1")
            prof=(await client.get(route(section,student)+extra)).json()
            await login(client,"student1")
            own=(await client.get(f"/api/v1/sections/{section}/my-learning"+extra)).json()
            item=own["items"][0]
            assert item["valid_recent"]==expected
            assert item["learning"]=={k:prof["concepts"][0]["learning"][k] for k in item["learning"]}
            assert (own["date_from"],own["date_to"])==(prof["date_from"],prof["date_to"])
            if not extra:
                assert boundary.id in [e["attempt_id"] for e in item["learning"]["evidence"]]
                assert outside.id not in [e["attempt_id"] for e in item["learning"]["evidence"]]
                assert item["learning"]["state"]=="insufficient"
        for endpoint in ["my-learning","my-practice"]:
            assert (await client.get(f"/api/v1/sections/{old.id}/{endpoint}")).status_code==404
            assert (await client.get(f"/api/v1/sections/{section}/{endpoint}?date_from=2020-01-01")).status_code==422
        assert before==session.scalar(select(func.count()).select_from(Job))

async def test_practice_real_pages_summary_privacy_and_permissions(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        section,student,q,material,version=await setup(client,session)
        chunk=session.get(Chunk,q.sources[0]["chunk_id"])
        q.sources=[{"chunk_id":chunk.id,"quote":chunk.content[:30]}]
        for i in range(103): practice(session,section,student,q,version,i%2==0,moment=now()-timedelta(minutes=i))
        practice(session,section,student,q,version,True,independent=False)
        held=practice(session,section,student,q,version,False); held.status="held"; held.correct=None
        practice(session,section,student,q,version,True,moment=now()-timedelta(days=40))
        session.commit()
        prof=(await client.get(route(section,student))).json()
        await login(client,"student1")
        path=f"/api/v1/sections/{section}/my-practice"
        first=await client.get(path)
        assert first.status_code==200,first.text
        assert "no-store" in first.headers["cache-control"]
        data=first.json()
        assert data["summary"]==prof["practice_summary"]
        assert data["total"]==105 and len(data["items"])==10 and data["has_more"]
        seen=[]
        for offset in range(0,105,10):
            page=(await client.get(path,params={"offset":offset})).json()
            seen.extend(a["id"] for a in page["items"])
        assert len(seen)==len(set(seen))==105
        assert not (await client.get(path,params={"offset":100})).json()["has_more"]
        assert all(a["source"].startswith("# never executed") for a in data["items"])
        assert all(a["source_available"] and a["feedback"] for a in data["items"])
        assert all("reference" not in a and "tests" not in a for a in data["items"])
        material.visibility="private"; session.commit()
        hidden=(await client.get(path)).json()
        assert hidden["summary"]==data["summary"]
        assert all(not a["source_available"] and a["feedback"] is None and a["title"]=="공개 범위가 변경된 실습" for a in hidden["items"])
        other=session.scalar(select(User).where(User.login_id=="student2"))
        session.add(Enrollment(student_id=other.id,section_id=section,course_id=q.course_id,status="active"));session.commit()
        await login(client,"student2")
        assert (await client.get(path)).json()["items"]==[]
        await login(client,"teacher1")
        assert (await client.get(path)).status_code==404
