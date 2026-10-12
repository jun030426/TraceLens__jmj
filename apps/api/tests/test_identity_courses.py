import httpx
import pytest
from lerny.models import Enrollment, User
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def login(client, name):
    response = await client.post(
        "/api/v1/auth/login", json={"login_id": name, "password": "Test-only-password-123"}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


async def setup_course(client):
    term = await client.post(
        "/api/v1/terms",
        json={"name": "검증 학기", "starts_on": "2026-01-01", "ends_on": "2099-12-31"},
    )
    assert term.status_code == 201, term.text
    course = await client.post(
        "/api/v1/courses",
        json={"term_id": term.json()["id"], "title": "자료구조", "teaching_language": "python"},
    )
    assert course.status_code == 201, course.text
    section = await client.post(
        f"/api/v1/courses/{course.json()['id']}/sections", json={"title": "1분반"}
    )
    assert section.status_code == 201
    return course.json(), section.json()


async def test_signup_cannot_grant_teacher_role(app_db):
    app, _ = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        payload = {
            "login_id": "newstudent",
            "password": "Test-only-password-123",
            "display_name": "학생",
            "email": "student@example.com", "privacy_notice_version": "2026-10-12",
        }
        assert (
            await c.post("/api/v1/auth/signup", json={**payload, "role": "teacher"})
        ).status_code == 422
        assert (await c.post("/api/v1/auth/signup", json=payload)).status_code == 201
        await login(c, "newstudent")
        assert (await c.get("/api/v1/me")).json()["role"] == "student"
        assert (
            await c.post(
                "/api/v1/terms",
                json={"name": "x", "starts_on": "2026-01-01", "ends_on": "2099-01-01"},
            )
        ).status_code == 403


async def test_csrf_and_cross_origin_enforced(app_db):
    app, _ = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        del c.headers["X-CSRF-Token"]
        assert (await c.post("/api/v1/auth/logout")).status_code == 403
        csrf = (await c.get("/api/v1/auth/csrf")).json()["csrf_token"]
        c.headers["X-CSRF-Token"] = csrf
        assert (
            await c.post("/api/v1/auth/logout", headers={"Origin": "https://evil.invalid"})
        ).status_code == 403
        assert (await c.post("/api/v1/auth/logout")).status_code == 204
        assert (await c.get("/api/v1/me")).status_code == 401


async def test_teacher_isolation_and_permission_revocation(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, section = await setup_course(c)
        other = session.scalar(select(User).where(User.login_id == "teacher2"))
        permission = {
            "teacher_id": other.id,
            "can_analyze": True,
            "can_edit": False,
            "active": True,
        }
        assert (
            await c.post(f"/api/v1/courses/{course['id']}/staff", json=permission)
        ).status_code == 200
        await login(c, "teacher2")
        assert (await c.get(f"/api/v1/sections/{section['id']}/enrollments")).status_code == 200
        assert (
            await c.post(f"/api/v1/courses/{course['id']}/sections", json={"title": "침입"})
        ).status_code == 403
        await login(c, "teacher1")
        await c.patch(f"/api/v1/courses/{course['id']}/staff", json={**permission, "active": False})
        await login(c, "teacher2")
        assert (await c.get(f"/api/v1/courses/{course['id']}")).status_code == 404


async def test_enrollment_transfer_preserves_history_and_cancel_revokes(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, section = await setup_course(c)
        second = (
            await c.post(f"/api/v1/courses/{course['id']}/sections", json={"title": "2분반"})
        ).json()
        code = (await c.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()[
            "join_code"
        ]
        await login(c, "student1")
        enrolled = await c.post("/api/v1/enrollments", json={"join_code": code})
        assert enrolled.status_code == 201
        entry_id = enrolled.json()["id"]
        assert (await c.get(f"/api/v1/courses/{course['id']}")).status_code == 200
        await login(c, "student2")
        assert (await c.get(f"/api/v1/courses/{course['id']}")).status_code == 404
        assert (await c.delete(f"/api/v1/enrollments/{entry_id}")).status_code == 404
        await login(c, "teacher1")
        transferred = await c.post(
            f"/api/v1/enrollments/{entry_id}/transfer", json={"target_section_id": second["id"]}
        )
        assert transferred.status_code == 200
        old = session.get(Enrollment, entry_id)
        assert old.section_id == section["id"] and old.status == "transferred"
        await login(c, "student1")
        assert len((await c.get("/api/v1/classrooms")).json()["items"]) == 1
        assert (
            await c.delete("/api/v1/enrollments/" + transferred.json()["id"])
        ).status_code == 204
        assert (await c.get(f"/api/v1/courses/{course['id']}")).status_code == 404


async def test_password_reset_is_one_time_and_revokes_sessions(app_db):
    app, session = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "operator1")
        teacher = session.scalar(select(User).where(User.login_id == "teacher1"))
        token = (
            await c.post(f"/api/v1/ops/users/{teacher.id}/reset-token", json={"reason": "test"})
        ).json()["one_time_token"]
        await login(c, "teacher1")
        payload = {"one_time_token": token, "new_password": "Different-test-password-123"}
        assert (await c.post("/api/v1/auth/reset-password", json=payload)).status_code == 204
        assert (await c.get("/api/v1/me")).status_code == 401
        assert (await c.post("/api/v1/auth/reset-password", json=payload)).status_code == 400


async def test_optimistic_course_update(app_db):
    app, _ = app_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await login(c, "teacher1")
        course, _ = await setup_course(c)
        path = f"/api/v1/courses/{course['id']}"
        body = {"title": "알고리즘", "teaching_language": "c"}
        assert (await c.patch(path, json=body)).status_code == 428
        assert (await c.patch(path, json=body, headers={"If-Match": "1"})).status_code == 200
        assert (await c.patch(path, json=body, headers={"If-Match": "1"})).status_code == 409


async def test_student_classroom_context_obeys_schedule_and_manual_progress(app_db):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from lerny.models import Section

    app, session = app_db
    day = datetime.now(ZoneInfo("Asia/Seoul")).date()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await login(c, "teacher1")
        _, section = await setup_course(c)
        code = (await c.post(f"/api/v1/sections/{section['id']}/join-code", json={})).json()["join_code"]
        model = session.get(Section, section["id"])
        model.week_schedule = [
            {"week": 1, "date": (day - timedelta(days=14)).isoformat()},
            {"week": 2, "date": day.isoformat()},
            {"week": 3, "date": (day + timedelta(days=7)).isoformat()},
        ]
        session.commit()
        await login(c, "student1")
        assert (await c.post("/api/v1/enrollments", json={"join_code": code})).status_code == 201
        room = (await c.get("/api/v1/classrooms")).json()["items"][0]
        assert room["teacher_name"] == "teacher1"
        assert room["current_week"] == 2
        model.progress_mode, model.progress_week = "manual", 1
        session.commit()
        assert (await c.get("/api/v1/classrooms")).json()["items"][0]["current_week"] == 1
        model.progress_week = None
        session.commit()
        assert (await c.get("/api/v1/classrooms")).json()["items"][0]["current_week"] is None
        assert (await c.get(f"/api/v1/sections/{section['id']}/weekly-progress")).status_code == 404
        await login(c, "student2")
        assert (await c.get("/api/v1/classrooms")).json()["items"] == []


async def test_optional_profile_and_normalized_photo(app_db):
    import base64
    import io
    from PIL import Image
    app, session = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await login(c, "student1")
        response = await c.patch("/api/v1/me/profile", json={"major": "컴퓨터공학과", "student_number": "001234"})
        assert response.status_code == 200, response.text
        assert response.json()["student_number"] == "001234"
        assert (await c.patch("/api/v1/me/profile", json={"role": "teacher"})).status_code == 422
        assert (await c.patch("/api/v1/me/profile", json={"avatar": "data:image/svg+xml;base64,AAAA"})).status_code == 422
        data = io.BytesIO()
        Image.new("RGB", (80, 60), "blue").save(data, format="PNG")
        photo = "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()
        result = await c.patch("/api/v1/me/profile", json={"avatar": photo})
        assert result.status_code == 200
        saved = (await c.get("/api/v1/me")).json()
        assert saved["avatar"].startswith("data:image/jpeg;base64,")
        assert saved["major"] == "컴퓨터공학과"
        await login(c, "student2")
        assert (await c.get("/api/v1/me")).json()["avatar"] is None
        await login(c, "student1")
        assert (await c.patch("/api/v1/me/profile", json={"avatar": None})).json()["avatar"] is None


async def test_signup_preserves_academic_fields(app_db):
    app, _ = app_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/api/v1/auth/signup", json={"login_id": "academicstudent", "password": "Test-only-password-123", "display_name": "학생", "major": "컴퓨터공학과", "student_number": "001234", "email": "student@example.com", "privacy_notice_version": "2026-10-12"})
        assert response.status_code == 201, response.text
        await login(c, "academicstudent")
        user = (await c.get("/api/v1/me")).json()
        assert user["major"] == "컴퓨터공학과"
        assert user["student_number"] == "001234"
        assert user["avatar"] is None
        assert user["email"] == "student@example.com"
        assert (await c.patch("/api/v1/me/profile", json={"email": "invalid"})).status_code == 422
        assert (await c.patch("/api/v1/me/profile", json={"email": "updated@example.com"})).json()["email"] == "updated@example.com"
