"""Exercise practice variant submissions across entry points and plans."""
import asyncio
import hashlib
from threading import Barrier

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lerny import practice
from lerny.models import ContentGeneration, PracticeAttempt, PracticeExercise
from test_cloud import cloud_db  # noqa: F401
from test_personal_pipeline import prepared


async def prepare_test_data(c, db, monkeypatch, week=3):
    code = "n = 3\nprint(n + 1)"
    course, section, material, version, chunk, student = await prepared(c, db, monkeypatch)
    generation = db.scalar(select(ContentGeneration).where(ContentGeneration.course_id == course["id"]))
    section.progress_week = material.week = generation.week = week
    chunk.content = code
    tests = [{"statement": "n = 3", "input": "n = 3", "expected": "4"},
             {"statement": "n = 3", "input": "n = 7", "expected": "8"}]
    for kind, template in [("blank", "n = 3\n[[빈칸]]"), ("full", "n = 3\n# 여기에 구현하세요.")]:
        db.add(PracticeExercise(course_id=course["id"], version_id=version.id, generation_id=generation.id,
            source_key=hashlib.sha256(code.encode()).hexdigest(), position=1, kind=kind, language="python",
            title="다음 정수 출력하기", prompt="주어진 정수보다 1 큰 수를 출력하세요.", template=template,
            reference=code, blanks={"1": "print(n + 1)"} if kind == "blank" else {}, tests=tests,
            sources=[{"chunk_id": chunk.id, "quote": code}], status="ready"))
    db.commit()
    base = f"/api/v1/sections/{section.id}"
    daily = (await c.post(base + "/practice/daily")).json()
    archive = (await c.post(base + f"/quiz-archive/{week}/practice")).json()
    problem = daily["items"][0]
    blank_id = problem["variants"]["blank"]["exercise_id"]
    full_id = problem["variants"]["full"]["exercise_id"]
    return {
        "course": course,
        "section": section,
        "base": base,
        "daily": daily,
        "archive": archive,
        "blank_id": blank_id,
        "full_id": full_id,
        "code": code,
        "student": student,
    }


@pytest.mark.asyncio
async def test_different_variant_submission_allowed(cloud_db, monkeypatch):
    """(a) 다른 변형은 제출 허용: 같은 문제라도 blank와 full 변형은 각각 1회씩 제출할 수 있다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"

            r1 = await c.post(submit, json={"exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "submit-blank"})
            assert r1.status_code == 202

            r2 = await c.post(submit, json={"exercise_id": ctx["full_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "submit-full"})
            assert r2.status_code == 202

            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 2


@pytest.mark.asyncio
async def test_same_variant_duplicate_submission_denied(cloud_db, monkeypatch):
    """(b) 같은 변형 재제출은 409: 이미 제출한 동일한 변형을 다시 제출하면 409로 차단된다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"

            r1 = await c.post(submit, json={"exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "sub-1"})
            assert r1.status_code == 202

            r2 = await c.post(submit, json={"exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "sub-2"})
            assert r2.status_code == 409


@pytest.mark.asyncio
async def test_same_variant_across_sessions_denied(cloud_db, monkeypatch):
    """(c) 세션이 달라도 같은 변형은 409: 일일 실습에서 제출한 변형은 주차 보관함에서 제출해도 409로 차단된다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"

            r1 = await c.post(submit, json={"plan_id": ctx["daily"]["id"], "exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "sub-daily"})
            assert r1.status_code == 202

            r2 = await c.post(submit, json={"plan_id": ctx["archive"]["id"], "exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "sub-archive"})
            assert r2.status_code == 409


@pytest.mark.asyncio
async def test_archive_view_answer_after_daily_submission(cloud_db, monkeypatch):
    """(d) 보관함 답지 조회 200: 일일 실습에서 제출한 변형은 보관함 세션에서도 답지(kind: answer) 조회가 200으로 성공한다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"
            help_url = ctx["base"] + "/practice/help"

            r1 = await c.post(submit, json={"plan_id": ctx["daily"]["id"], "exercise_id": ctx["blank_id"], "source": ctx["code"]},
                              headers={"Idempotency-Key": "sub-daily-for-ans"})
            assert r1.status_code == 202

            ans_blank = await c.post(help_url, json={"plan_id": ctx["archive"]["id"], "exercise_id": ctx["blank_id"], "kind": "answer"})
            assert ans_blank.status_code == 200
            assert ans_blank.json()["explanation"]["reference"] == ctx["code"]

            ans_full = await c.post(help_url, json={"plan_id": ctx["archive"]["id"], "exercise_id": ctx["full_id"], "kind": "answer"})
            assert ans_full.status_code == 409

            hint_blank = await c.post(help_url, json={"plan_id": ctx["archive"]["id"], "exercise_id": ctx["blank_id"], "kind": "hint", "step": 1})
            assert hint_blank.status_code == 409

            hint_full = await c.post(help_url, json={"plan_id": ctx["archive"]["id"], "exercise_id": ctx["full_id"], "kind": "hint", "step": 1})
            assert hint_full.status_code == 200
