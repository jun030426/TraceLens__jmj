"""Current-thread pagination must preserve archives and student ownership."""

from datetime import timedelta

import httpx
import pytest
from lerny.models import ChatMessage, User, now
from sqlalchemy import select
from test_identity_courses import login, setup_course


@pytest.mark.asyncio
async def test_current_thread_history_paginates_without_mixing_archives(app_db):
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await login(client, "teacher1")
        course, section = await setup_course(client)
        code = (await client.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()["join_code"]
        await login(client, "student1")
        assert (await client.post("/api/v1/enrollments", json={"join_code": code})).status_code == 201
        student = session.scalar(select(User).where(User.login_id == "student1"))
        other = session.scalar(select(User).where(User.login_id == "student2"))
        started = now() - timedelta(hours=1)
        for index in range(35):
            session.add(ChatMessage(
                student_id=student.id, section_id=section["id"],
                thread_id="older-thread" if index < 5 else "current-thread",
                question=f"질문 {index}", answer={"answer": "합성 답변", "citations": []},
                access_epoch=course["access_epoch"], created_at=started + timedelta(seconds=index),
            ))
        session.add(ChatMessage(
            student_id=other.id, section_id=section["id"], thread_id="other-student-thread",
            question="다른 학생의 비공개 질문", access_epoch=course["access_epoch"],
        ))
        session.commit()
        path = f"/api/v1/sections/{section['id']}/chat/history"
        current = (await client.get(path, params={"latest_thread": True, "limit": 20})).json()
        assert current["thread_id"] == "current-thread"
        assert current["total"] == 30 and current["has_more"] is True
        assert [item["question"] for item in current["items"]] == [f"질문 {i}" for i in range(15, 35)]
        earlier = (await client.get(path, params={"thread_id": "current-thread", "limit": 20, "offset": 20})).json()
        assert [item["question"] for item in earlier["items"]] == [f"질문 {i}" for i in range(5, 15)]
        assert earlier["has_more"] is False
        assert (await client.get(path)).json()["total"] == 35
        assert (await client.get(path, params={"thread_id": "other-student-thread"})).json()["items"] == []
        await login(client, "student2")
        assert (await client.get(path)).status_code == 404
