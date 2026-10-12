import secrets
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Header
from pydantic import Field, model_validator
from sqlalchemy import select

from lerny.auth import Input
from lerny.models import AuditEvent, Course, CourseStaff, Enrollment, Section, Term, User, now
from lerny.security import Actor, Db, course_access, deny, digest, match_revision, staff_access

router = APIRouter(prefix="/api/v1")


def view(record, fields):
    return {key: getattr(record, key) for key in fields.split()}


def course_view(course):
    return view(course, "id title term_id lead_teacher_id teaching_language revision access_epoch")


def section_view(section):
    return view(section, "id course_id title progress progress_mode progress_week revision approval_required")


def audit(session, actor, action, target, detail=None):
    session.add(AuditEvent(actor_id=actor.id, action=action, target_id=target, detail=detail or {}))


class TermInput(Input):
    name: str = Field(min_length=1, max_length=100)
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("종료일은 시작일 이후여야 합니다.")
        return self


@router.get("/terms")
def terms(session: Db, actor: Actor):
    return {
        "items": [
            view(t, "id name starts_on ends_on")
            for t in session.scalars(select(Term).order_by(Term.starts_on.desc()))
        ]
    }


@router.post("/terms", status_code=201)
def create_term(body: TermInput, session: Db, actor: Actor):
    if actor.role not in ("teacher", "operator"):
        deny()
    term = Term(**body.model_dump())
    session.add(term)
    session.flush()
    audit(session, actor, "term_created", term.id)
    session.commit()
    return view(term, "id name starts_on ends_on")


class CourseInput(Input):
    term_id: str
    title: str = Field(min_length=1, max_length=200)
    teaching_language: Literal["c", "java", "python"]


@router.post("/courses", status_code=201)
def create_course(body: CourseInput, session: Db, actor: Actor):
    if actor.role != "teacher":
        deny()
    if not session.get(Term, body.term_id):
        deny(422, "학기를 먼저 선택해 주세요.")
    course = Course(**body.model_dump(), lead_teacher_id=actor.id)
    session.add(course)
    session.flush()
    audit(session, actor, "course_created", course.id)
    session.commit()
    return course_view(course)


@router.get("/courses")
def list_courses(session: Db, actor: Actor):
    if actor.role != "teacher":
        return {"items": []}
    shared = select(CourseStaff.course_id).where(
        CourseStaff.teacher_id == actor.id, CourseStaff.active.is_(True)
    )
    courses = session.scalars(
        select(Course)
        .where((Course.lead_teacher_id == actor.id) | Course.id.in_(shared))
        .order_by(Course.created_at)
    )
    return {"items": [course_view(c) for c in courses]}


@router.get("/courses/{course_id}")
def get_course(course_id: str, session: Db, actor: Actor):
    return course_view(course_access(session, actor, course_id))


class CourseEdit(Input):
    title: str = Field(min_length=1, max_length=200)
    teaching_language: Literal["c", "java", "python"]


@router.patch("/courses/{course_id}")
def edit_course(
    course_id: str,
    body: CourseEdit,
    session: Db,
    actor: Actor,
    if_match: str | None = Header(default=None),
):
    staff_access(session, actor, course_id)
    course = session.scalar(select(Course).where(Course.id == course_id).with_for_update())
    match_revision(course.revision, if_match)
    course.title, course.teaching_language = body.title, body.teaching_language
    course.revision += 1
    session.commit()
    return course_view(course)


class Title(Input):
    title: str = Field(min_length=1, max_length=100)


@router.post("/courses/{course_id}/sections", status_code=201)
def create_section(course_id: str, body: Title, session: Db, actor: Actor):
    staff_access(session, actor, course_id)
    section = Section(course_id=course_id, title=body.title)
    session.add(section)
    session.flush()
    from lerny.automatic import sync_progress
    sync_progress(session, course_id)
    audit(session, actor, "section_created", section.id)
    session.commit()
    return section_view(section)


@router.get("/courses/{course_id}/sections")
def sections(course_id: str, session: Db, actor: Actor):
    staff_access(session, actor, course_id, "read")
    from lerny.automatic import sync_progress
    sync_progress(session, course_id)
    session.commit()
    return {
        "items": [
            section_view(s)
            for s in session.scalars(
                select(Section).where(Section.course_id == course_id).order_by(Section.created_at)
            )
        ]
    }


def section_staff(session, actor, section_id, permission="edit"):
    section = session.get(Section, section_id)
    if not section:
        deny(404)
    staff_access(session, actor, section.course_id, permission)
    return section


class CodeInput(Input):
    expires_at: datetime | None = None
    approval_required: bool = False


@router.post("/sections/{section_id}/join-code")
def join_code(section_id: str, body: CodeInput, session: Db, actor: Actor):
    section = section_staff(session, actor, section_id)
    if body.expires_at and (body.expires_at.tzinfo is None or body.expires_at <= now()):
        deny(422, "만료 시각은 시간대가 있는 미래 시각이어야 합니다.")
    code = secrets.token_urlsafe(12)
    section.join_code_hash = digest(code)
    section.join_expires_at = body.expires_at or now() + timedelta(days=30)
    section.approval_required = body.approval_required
    audit(session, actor, "join_code_rotated", section_id)
    session.commit()
    return {"join_code": code, "expires_at": section.join_expires_at}


class EnrollInput(Input):
    join_code: str = Field(min_length=8, max_length=100)


@router.post("/enrollments", status_code=201)
def enroll(body: EnrollInput, session: Db, actor: Actor):
    if actor.role != "student":
        deny()
    section = session.scalar(
        select(Section).where(
            Section.join_code_hash == digest(body.join_code), Section.join_expires_at > now()
        )
    )
    if not section:
        deny(404, "유효한 수강 코드가 아닙니다.")
    term = session.get(Term, session.get(Course, section.course_id).term_id)
    if term.ends_on < now().date():
        deny(409, "종료된 학기입니다.")
    entry = Enrollment(
        student_id=actor.id,
        course_id=section.course_id,
        section_id=section.id,
        status="pending" if section.approval_required else "active",
    )
    session.add(entry)
    session.flush()
    audit(session, actor, "enrollment_created", entry.id)
    session.commit()
    return view(entry, "id section_id course_id status")


@router.get("/classrooms")
def classrooms(session: Db, actor: Actor):
    from lerny.automatic import calendar_week

    entries = session.execute(
        select(Enrollment, Section, Course, Term, User.display_name)
        .join(Section, Enrollment.section_id == Section.id)
        .join(Course, Enrollment.course_id == Course.id)
        .join(Term, Course.term_id == Term.id)
        .join(User, Course.lead_teacher_id == User.id)
        .where(Enrollment.student_id == actor.id, Enrollment.status.in_(["active", "pending"]))
        .order_by(Enrollment.created_at)
    ).all()
    return {
        "items": [
            {
                "enrollment_id": e.id,
                "status": e.status,
                "section": section_view(s),
                "course": course_view(c),
                "term": view(t, "id name starts_on ends_on"),
                "teacher_name": teacher_name,
                "current_week": calendar_week(session, s)
                if s.progress_mode == "auto" else s.progress_week,
            }
            for e, s, c, t, teacher_name in entries
        ]
    }


@router.delete("/enrollments/{entry_id}", status_code=204)
def cancel_enrollment(entry_id: str, session: Db, actor: Actor):
    entry = session.scalar(select(Enrollment).where(Enrollment.id == entry_id).with_for_update())
    if not entry or entry.student_id != actor.id:
        deny(404)
    entry.status, entry.valid_to = "cancelled", now()
    audit(session, actor, "enrollment_cancelled", entry.id)
    session.commit()


@router.get("/sections/{section_id}/enrollments")
def roster(section_id: str, session: Db, actor: Actor):
    section_staff(session, actor, section_id, "analyze")
    rows = session.execute(
        select(Enrollment, User)
        .join(User, Enrollment.student_id == User.id)
        .where(Enrollment.section_id == section_id)
        .order_by(Enrollment.created_at)
    )
    return {
        "items": [
            dict(
                view(e, "id student_id status valid_to"),
                display_name=u.display_name,
                login_id=u.login_id,
            )
            for e, u in rows
        ]
    }


@router.post("/enrollments/{entry_id}/approve")
def approve(entry_id: str, session: Db, actor: Actor):
    entry = session.scalar(select(Enrollment).where(Enrollment.id == entry_id).with_for_update())
    if not entry:
        deny(404)
    staff_access(session, actor, entry.course_id)
    if entry.status != "pending":
        deny(409, "승인 대기 상태가 아닙니다.")
    entry.status = "active"
    audit(session, actor, "enrollment_approved", entry.id)
    session.commit()
    return view(entry, "id status section_id")


class Transfer(Input):
    target_section_id: str


@router.post("/enrollments/{entry_id}/transfer")
def transfer(entry_id: str, body: Transfer, session: Db, actor: Actor):
    entry = session.scalar(select(Enrollment).where(Enrollment.id == entry_id).with_for_update())
    if not entry:
        deny(404)
    staff_access(session, actor, entry.course_id)
    target = session.get(Section, body.target_section_id)
    if not target or target.course_id != entry.course_id:
        deny(422, "같은 과목의 분반만 선택할 수 있습니다.")
    if entry.status != "active" or entry.section_id == target.id:
        deny(409, "이동할 수 없는 수강 상태입니다.")
    entry.status, entry.valid_to = "transferred", now()
    session.flush()
    new = Enrollment(student_id=entry.student_id, course_id=entry.course_id, section_id=target.id)
    session.add(new)
    session.flush()
    audit(session, actor, "enrollment_transferred", entry.id, {"new_enrollment_id": new.id})
    session.commit()
    return view(new, "id course_id section_id status")


class StaffInput(Input):
    teacher_id: str
    can_analyze: bool
    can_edit: bool
    active: bool = True


@router.post("/courses/{course_id}/staff")
@router.patch("/courses/{course_id}/staff")
def staff(course_id: str, body: StaffInput, session: Db, actor: Actor):
    course = staff_access(session, actor, course_id)
    if course.lead_teacher_id != actor.id:
        deny()
    teacher = session.get(User, body.teacher_id)
    if not teacher or teacher.role != "teacher" or not teacher.active:
        deny(422, "발급된 교수 계정이 필요합니다.")
    if teacher.id == actor.id:
        deny(422, "대표 교수는 공동 교수로 등록하지 않습니다.")
    item = session.scalar(
        select(CourseStaff)
        .where(CourseStaff.course_id == course_id, CourseStaff.teacher_id == teacher.id)
        .with_for_update()
    )
    if not item:
        item = CourseStaff(course_id=course_id, teacher_id=teacher.id)
        session.add(item)
    item.can_analyze, item.can_edit, item.active = body.can_analyze, body.can_edit, body.active
    course.access_epoch += 1
    audit(session, actor, "staff_updated", course_id, body.model_dump())
    session.commit()
    return body
