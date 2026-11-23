"""Each variant (blank / full) of a practice problem is submitted once, independently."""
import asyncio
import hashlib
from threading import Barrier

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lerny import practice
from lerny.models import ContentGeneration, Job, LearningCompletion, PracticeAttempt, PracticeExercise
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
    monkeypatch.setattr(practice, "output_of", lambda lang, src, **kw: "8" if "n = 7" in src else "4")
    base = f"/api/v1/sections/{section.id}"
    daily = (await c.post(base + "/practice/daily")).json()
    archive = (await c.post(base + f"/quiz-archive/{week}/practice")).json()
    problem = daily["items"][0]
    return {
        "base": base,
        "daily": daily,
        "archive": archive,
        "blank_id": problem["variants"]["blank"]["exercise_id"],
        "full_id": problem["variants"]["full"]["exercise_id"],
        "code": code,
    }


def grade(db, response):
    """Run the queued grading job the way the interactive worker does."""
    result = practice.grade(db, db.get(Job, response.json()["job_id"]))
    db.commit()
    return result


def test_blank_offsets_use_utf16_code_units_and_exact_editor_boundaries():
    from lerny.practice_snapshot import SubmissionEditor, submission_snapshot

    template = " 한😀[[빈칸]]:[[빈칸]]\n"
    source = " 한😀가:🧪:나\n"
    editor = SubmissionEditor(template=template, fills=["가:🧪", "나"])
    assert practice.Submission(exercise_id="e", source=source, editor=editor).source == source
    assert submission_snapshot("blank", template, source, editor) == {
        "kind": "blank", "spans": [{"number": 1, "start": 4, "end": 8}, {"number": 2, "start": 9, "end": 10}]}
    assert submission_snapshot("blank", template, source, None) is None
    assert submission_snapshot("blank", "😀 [[빈칸]]", "😀 한", None)["spans"] == [
        {"number": 1, "start": 3, "end": 4}]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["blank", "full"])
async def test_feedback_uses_editor_lines_on_all_student_routes(cloud_db, monkeypatch, kind):
    from rag_mvp.cloze_generator import ClozeGenerator

    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            base = ctx["base"]
            exercise = db.get(PracticeExercise, ctx[kind + "_id"])
            statement = "# 원본 😀\n\nscore = 85.5"
            prefix = "\n \t\n" + statement
            template = prefix + "\n[[빈칸]]\n    grade = [[빈칸]]" if kind == "blank" else prefix
            exercise.template = template
            exercise.tests = [{"input": statement, "statement": statement, "expected": "B"}]
            exercise.reference = prefix + "\nif score >= 80:\n    grade = 'B'"
            exercise.blanks = {"1": "if score >= 80:", "2": "'B'"} if kind == "blank" else {}
            db.commit()
            fills = ["grade = '😀'", "'B'"]
            typed = prefix + "\n" + fills[0] + "\n    grade = " + fills[1]
            editor = {"template": template}
            if kind == "blank":
                editor["fills"] = fills
            # Simulate a tab opened before deployment, using the original grading template.
            res = await c.post(base + "/practice/submit", json={"exercise_id": exercise.id, "source": typed, "editor": editor},
                               headers={"Idempotency-Key": "before-display-change"})
            assert res.status_code == 202, res.text
            grade(db, res)
            attempt = db.get(PracticeAttempt, res.json()["id"])
            original_feedback = attempt.feedback
            snapshot = attempt.submission_snapshot
            saved = typed if kind == "blank" else typed.strip()
            visible = typed.split("\n", 2)[2] if kind == "blank" else typed
            line = ClozeGenerator.check_ast_syntax(visible)["error_line"]
            assert line == (5 if kind == "blank" else 7)
            assert original_feedback["syntax"]["error_line"] != line
            if kind == "blank":
                encoded = saved.encode("utf-16-le")
                assert [encoded[s["start"]*2:s["end"]*2].decode("utf-16-le") for s in snapshot["spans"]] == fills
            for page in [base + "/practice/daily", base + "/quiz-archive/3/practice"]:
                problem, = (await c.post(page)).json()["items"]
                v = problem["variants"][kind]
                replay = v["attempt"]["replay_source"]
                assert ClozeGenerator.check_ast_syntax(replay)["error_line"] == line
                assert v["attempt"]["feedback"]["message"].startswith(f"{line}번째 줄")
            for path in ["/practice/attempts", "/my-practice"]:
                item, = (await c.get(base + path)).json()["items"]
                assert item["feedback"]["message"].startswith(f"{line}번째 줄")
                assert item["feedback"]["syntax"]["error_line"] == line
                assert item["feedback"]["syntax"]["error_message"] == item["feedback"]["message"]
                assert item["source"] == saved and item["submission_snapshot"] == snapshot
            db.refresh(attempt)
            assert attempt.feedback == original_feedback and attempt.submission_snapshot == snapshot
            # Older attempts may only carry the worker's human-readable error.
            attempt.feedback = {"message": original_feedback["message"]}
            db.commit()
            item, = (await c.get(base + "/practice/attempts")).json()["items"]
            assert item["feedback"] == {"message": original_feedback["message"].replace(
                f'{original_feedback["syntax"]["error_line"]}번째 줄', f"{line}번째 줄", 1)}


@pytest.mark.asyncio
@pytest.mark.parametrize("leading,with_editor", [("  ", False), ("\n\n", True), ("\n\n  ", True)])
async def test_full_submission_keeps_legacy_grading_whitespace(cloud_db, monkeypatch, leading, with_editor):
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            code = "n = 3\nif n:\n    print(n + 1)"
            starter = ctx["daily"]["items"][0]["variants"]["full"]["template"]
            body = {"exercise_id": ctx["full_id"], "source": leading + code + "\n  "}
            if with_editor:
                body["editor"] = {"template": starter}
            response = await c.post(ctx["base"] + "/practice/submit", json=body,
                                    headers={"Idempotency-Key": "full-whitespace"})
            assert response.status_code == 202
            assert response.json()["source"] == code
            attempt = db.get(PracticeAttempt, response.json()["id"])
            assert attempt.source == code
            expected = {"kind": "full", "starter_code": starter}
            if leading.count("\n"):
                expected["editor_leading_lines"] = leading.count("\n")
            assert attempt.submission_snapshot == expected
            assert grade(db, response)["correct"] is True


@pytest.mark.asyncio
async def test_submission_snapshots_survive_template_changes_on_both_routes(cloud_db, monkeypatch):
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            variants = ctx["daily"]["items"][0]["variants"]
            route = ctx["base"] + "/practice/submit"
            template = variants["blank"]["template"]
            value = "print(n + 1) # 😀"
            source = template.replace("[[빈칸]]", value)
            body = {"exercise_id": ctx["blank_id"], "source": source,
                    "editor": {"template": template, "fills": [value]}}
            for editor, status in [({"template": "old", "fills": [value]}, 409),
                                   ({"template": template, "fills": ["wrong"]}, 422)]:
                invalid = await c.post(route, json={**body, "editor": editor}, headers={"Idempotency-Key": "check"})
                assert invalid.status_code == status
            first = await c.post(route, json=body, headers={"Idempotency-Key": "blank-snapshot"})
            assert first.status_code == 202, first.text
            grade(db, first)
            starter = variants["full"]["template"]
            second = await c.post(route, json={"exercise_id": ctx["full_id"], "source": "\n\n  " + ctx["code"] + "\n",
                                               "editor": {"template": starter}},
                                  headers={"Idempotency-Key": "full-snapshot"})
            assert second.status_code == 202, second.text
            assert grade(db, second)["correct"] is True
            start = len(source.partition(value)[0].encode("utf-16-le")) // 2
            expected = {first.json()["id"]: {"kind": "blank", "spans": [
                {"number": 1, "start": start, "end": start + len(value.encode("utf-16-le")) // 2}]},
                second.json()["id"]: {"kind": "full", "starter_code": starter, "editor_leading_lines": 2}}
            for ex in (ctx["blank_id"], ctx["full_id"]):
                db.get(PracticeExercise, ex).template = "changed after submission"
            db.commit()
            for legacy in (False, True):
                if legacy:
                    db.get(PracticeAttempt, first.json()["id"]).submission_snapshot = None
                    db.commit()
                    expected[first.json()["id"]] = None
                for path in ("/practice/attempts", "/my-practice"):
                    result = await c.get(ctx["base"] + path)
                    assert result.status_code == 200, result.text
                    items = result.json()["items"]
                    assert {i["id"]: i["submission_snapshot"] for i in items} == expected
                    assert next(i["source"] for i in items if i["id"] == second.json()["id"]) == ctx["code"]


@pytest.mark.asyncio
async def test_each_variant_is_submitted_independently(cloud_db, monkeypatch):
    """(a) 같은 문제의 빈칸·전체 구현은 각각 한 번씩 제출하고, 화면에 유형별 제출 기록을 준다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            base, blank, full, code = ctx["base"], ctx["blank_id"], ctx["full_id"], ctx["code"]
            submit = base + "/practice/submit"
            progress = "/api/v1/my/practice-progress"
            problem, = ctx["daily"]["items"]
            assert blank != full and problem["submitted_exercise_id"] is None and problem["attempt"] is None
            assert all(v["attempt"] is None for v in problem["variants"].values())

            first = await c.post(submit, json={"exercise_id": blank, "source": code},
                                 headers={"Idempotency-Key": "submit-blank"})
            assert first.status_code == 202 and first.json()["independent"] is True
            # Only one submission is verified at a time, whichever variant or problem it is.
            waiting = await c.post(submit, json={"exercise_id": full, "source": code},
                                   headers={"Idempotency-Key": "submit-full-early"})
            assert waiting.status_code == 409
            assert grade(db, first)["correct"]

            row, = (await c.post(base + "/practice/daily")).json()["items"]
            assert row["submitted_exercise_id"] == blank and row["attempt"]["exercise_id"] == blank
            assert row["variants"]["blank"]["attempt"]["status"] == "graded"
            assert row["variants"]["blank"]["attempt"]["source"] == code
            assert row["variants"]["full"]["attempt"] is None
            # The other variant stays open: its hints still work and its answer stays closed.
            state = await c.post(base + "/practice/help", json={"exercise_id": full, "kind": "state"})
            assert state.json()["submitted_exercise_id"] is None and state.json()["can_view_answer"] is False

            second = await c.post(submit, json={"exercise_id": full, "source": code},
                                  headers={"Idempotency-Key": "submit-full"})
            assert second.status_code == 202
            assert grade(db, second)["correct"]
            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 2

            for route in (base + "/practice/daily", base + "/quiz-archive/3/practice"):
                row, = (await c.post(route)).json()["items"]
                # Top-level fields keep describing the variant submitted first.
                assert row["submitted_exercise_id"] == blank
                assert {kind: v["attempt"]["exercise_id"] for kind, v in row["variants"].items()} == {
                    "blank": blank, "full": full}
            for plan in (ctx["daily"], ctx["archive"]):
                grouped = (await c.get(base + "/practice/attempts",
                                       params={"plan_id": plan["id"], "by_exercise": True})).json()["items"]
                assert [a["exercise_id"] for a in grouped] == [blank, full]
                item, = (await c.get(progress, params={"session_id": plan["id"]})).json()["items"]
                assert (item["total"], item["submitted"], item["remaining_exercise_ids"]) == (1, 1, [])
            # A problem still counts once however many of its variants are submitted.
            assert (await c.get("/api/v1/my/practice-submission-count")).json() == {"submitted": 1}
            assert db.scalar(select(func.count()).select_from(LearningCompletion)
                             .where(LearningCompletion.domain == "practice")) == 1


@pytest.mark.asyncio
async def test_same_variant_duplicate_submission_denied(cloud_db, monkeypatch):
    """(b) 같은 유형 재제출은 409: 동시에 보내도 한 건만 받고, 채점 뒤에도 다시 받지 않는다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"
            body = {"exercise_id": ctx["blank_id"], "source": ctx["code"]}
            # Both requests pass assignment checks before either acquires the submission lock.
            barrier = Barrier(2, timeout=10)
            assigned = practice.assigned
            def simultaneous(*args):
                result = assigned(*args)
                barrier.wait()
                return result
            with monkeypatch.context() as concurrent:
                concurrent.setattr(practice, "assigned", simultaneous)
                results = await asyncio.gather(*(c.post(submit, json=body,
                    headers={"Idempotency-Key": key}) for key in ("sub-1", "sub-2")))
            assert sorted(r.status_code for r in results) == [202, 409], [r.text for r in results]
            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 1
            assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "practice_grade")) == 1
            winner = next(r for r in results if r.status_code == 202)
            grade(db, winner)

            again = await c.post(submit, json=body, headers={"Idempotency-Key": "sub-3"})
            assert again.status_code == 409
            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 1


@pytest.mark.asyncio
async def test_same_variant_across_sessions_denied(cloud_db, monkeypatch):
    """(c) 세션이 달라도 같은 유형은 409: 일일 실습에서 제출한 유형은 주차 보관함에서도 다시 받지 않는다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"
            archive = ctx["archive"]["id"]

            # Today's assignment is addressed without plan_id. plan_id selects an archive session.
            daily = await c.post(submit, json={"exercise_id": ctx["blank_id"], "source": ctx["code"]},
                                 headers={"Idempotency-Key": "sub-daily"})
            assert daily.status_code == 202
            grade(db, daily)

            repeated = await c.post(submit, json={"plan_id": archive, "exercise_id": ctx["blank_id"],
                                                  "source": ctx["code"]}, headers={"Idempotency-Key": "sub-archive"})
            assert repeated.status_code == 409
            other = await c.post(submit, json={"plan_id": archive, "exercise_id": ctx["full_id"],
                                               "source": ctx["code"]}, headers={"Idempotency-Key": "sub-archive-full"})
            assert other.status_code == 202
            assert db.scalar(select(func.count()).select_from(PracticeAttempt)) == 2


@pytest.mark.asyncio
async def test_archive_view_answer_after_daily_submission(cloud_db, monkeypatch):
    """(d) 보관함 답지 조회: 일일 실습에서 제출한 유형만 보관함에서 답지를 열고, 다른 유형은 힌트만 열린다."""
    app, engine, _ = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lerny.example") as c:
        with Session(engine) as db:
            ctx = await prepare_test_data(c, db, monkeypatch)
            submit = ctx["base"] + "/practice/submit"
            help_url = ctx["base"] + "/practice/help"
            archive = ctx["archive"]["id"]

            daily = await c.post(submit, json={"exercise_id": ctx["blank_id"], "source": ctx["code"]},
                                 headers={"Idempotency-Key": "sub-daily-for-ans"})
            assert daily.status_code == 202
            grade(db, daily)

            ans_blank = await c.post(help_url, json={"plan_id": archive, "exercise_id": ctx["blank_id"], "kind": "answer"})
            assert ans_blank.status_code == 200
            assert ans_blank.json()["explanation"]["reference"] == ctx["code"]

            ans_full = await c.post(help_url, json={"plan_id": archive, "exercise_id": ctx["full_id"], "kind": "answer"})
            assert ans_full.status_code == 409

            hint_blank = await c.post(help_url, json={"plan_id": archive, "exercise_id": ctx["blank_id"], "kind": "hint", "step": 1})
            assert hint_blank.status_code == 409

            hint_full = await c.post(help_url, json={"plan_id": archive, "exercise_id": ctx["full_id"], "kind": "hint", "step": 1})
            assert hint_full.status_code == 200

            # Help used on any variant of the problem marks later attempts on it as assisted.
            assisted = await c.post(submit, json={"plan_id": archive, "exercise_id": ctx["full_id"],
                                                  "source": ctx["code"]}, headers={"Idempotency-Key": "sub-assisted"})
            assert assisted.status_code == 202 and assisted.json()["independent"] is False
