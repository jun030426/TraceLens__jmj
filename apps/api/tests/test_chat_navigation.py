from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from lerny.models import ChatMessage, Course, Job, User, now, uid
from test_identity_courses import login
from test_learning import seed

pytestmark = pytest.mark.asyncio


async def test_history_pages_search_and_permissions_preserve_old_questions(app_db):
    app, db = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course, section, _ = await seed(client, db)
        student = db.scalar(select(User).where(User.login_id == "student1"))
        other = db.scalar(select(User).where(User.login_id == "student2"))
        timestamp = now()
        messages = []
        for index in range(63):
            message = ChatMessage(student_id=student.id, section_id=section["id"], thread_id=uid(),
                question=f"큐 질문 {index:02}" if index else "100%_일치 오래된 질문",
                answer={"answer": "PUBLIC_ANSWER", "citations": []}, access_epoch=1,
                created_at=timestamp - timedelta(minutes=index))
            db.add(message)
            messages.append(message)
        db.add(ChatMessage(student_id=other.id, section_id=section["id"], thread_id=uid(),
            question="OTHER_STUDENT_SECRET", access_epoch=1))
        db.flush()
        pending = Job(owner_id=student.id, course_id=course["id"], kind="chat",
            payload={"message_id": messages[0].id})
        db.add(pending)
        db.commit()
        route = f"/api/v1/sections/{section['id']}/chat/history"
        first = (await client.get(route, params={"limit": 8})).json()
        assert first["total"] == 63 and first["has_more"]
        assert first["job_id"] == pending.id
        assert first["thread_id"] == messages[0].thread_id
        assert [item["id"] for item in first["items"]] == [m.id for m in reversed(messages[:8])]
        seen = []
        for offset in range(0, 64, 8):
            result = (await client.get(route, params={"limit": 8, "offset": offset})).json()
            seen.extend(item["id"] for item in result["items"])
        assert len(seen) == len(set(seen)) == 63
        assert result["has_more"] is False
        assert result["job_id"] is None
        old = (await client.get(route, params={"q": "질문 62"})).json()
        assert old["total"] == 1 and old["items"][0]["id"] == messages[-1].id
        literal = (await client.get(route, params={"q": "%_"})).json()
        assert literal["total"] == 1
        assert (await client.get(route, params={"q": "없는 검색어"})).json()["items"] == []
        for query in ({"limit": 51}, {"limit": 0}, {"offset": -1}, {"q": "a" * 201}):
            assert (await client.get(route, params=query)).status_code == 422
        db.get(Course, course["id"]).access_epoch += 1
        db.commit()
        revoked = (await client.get(route, params={"q": "질문 62"})).json()["items"][0]
        assert revoked["answer"] is None and revoked["error"]
        await login(client, "student2")
        assert (await client.get(route)).status_code == 404
