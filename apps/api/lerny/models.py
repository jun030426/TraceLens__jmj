import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Identity, Base):
    __tablename__ = "users"
    login_id: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    major: Mapped[str | None] = mapped_column(String(100))
    student_number: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    avatar: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="student")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_notice_version: Mapped[str] = mapped_column(String(20), default="2026-10-09")


class LoginSession(Identity, Base):
    __tablename__ = "login_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Identity, Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), index=True)


class ResetToken(Identity, Base):
    __tablename__ = "reset_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Term(Identity, Base):
    __tablename__ = "terms"
    name: Mapped[str] = mapped_column(String(100))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)


class Course(Identity, Base):
    __tablename__ = "courses"
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"))
    title: Mapped[str] = mapped_column(String(200))
    lead_teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    teaching_language: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    access_epoch: Mapped[int] = mapped_column(Integer, default=1)


class CourseStaff(Identity, Base):
    __tablename__ = "course_staff"
    __table_args__ = (Index("uq_course_teacher", "course_id", "teacher_id", unique=True),)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    can_analyze: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Section(Identity, Base):
    __tablename__ = "sections"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    join_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    join_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[list] = mapped_column(JSON, default=list)
    progress_mode: Mapped[str] = mapped_column(String(10), default="auto")
    week_schedule: Mapped[list] = mapped_column(JSON, default=list)
    progress_week: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Enrollment(Identity, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        Index(
            "uq_active_student_course",
            "student_id",
            "course_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'pending')"),
        ),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Material(Identity, Base):
    __tablename__ = "materials"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    week: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(10))
    internal_use: Mapped[str] = mapped_column(String(30), default="none")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active_version_id: Mapped[str | None] = mapped_column(String(36))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class MaterialVersion(Identity, Base):
    __tablename__ = "material_versions"
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    concept_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(50))


class Chunk(Identity, Base):
    __tablename__ = "chunks"
    version_id: Mapped[str] = mapped_column(ForeignKey("material_versions.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(JSON)
    embedding: Mapped[list | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String(100))


class Concept(Identity, Base):
    __tablename__ = "concepts"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Job(Identity, Base):
    __tablename__ = "jobs"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Identity, Base):
    __tablename__ = "chat_messages"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[dict | None] = mapped_column(JSON)
    access_epoch: Mapped[int] = mapped_column(Integer)


class Idempotency(Identity, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (Index("uq_idempotency_scope", "user_id", "scope", "key", unique=True),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class Question(Identity, Base):
    __tablename__ = "questions"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    kind: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    solution: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class LearningSession(Identity, Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        Index("uq_daily_student_section", "student_id", "section_id", "day", unique=True),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    day: Mapped[date] = mapped_column(Date)
    question_ids: Mapped[list] = mapped_column(JSON)


class Attempt(Identity, Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("uq_session_question_attempt", "learning_session_id", "question_id", unique=True),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    learning_session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    answer: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    score: Mapped[int | None] = mapped_column(Integer)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[dict | None] = mapped_column(JSON)
    independent: Mapped[bool] = mapped_column(Boolean, default=True)
    review_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    appealed: Mapped[bool] = mapped_column(Boolean, default=False)


class Review(Identity, Base):
    __tablename__ = "reviews"
    __table_args__ = (Index("uq_student_concept_review", "student_id", "concept_id", unique=True),)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    due_on: Mapped[date | None] = mapped_column(Date)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_day: Mapped[date | None] = mapped_column(Date)


class LearningCompletion(Identity, Base):
    __tablename__ = "learning_completions"
    __table_args__ = (Index("uq_completion_source", "student_id", "domain", "source_id", unique=True),)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    domain: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36))
    day: Mapped[date] = mapped_column(Date)


class ExamPlan(Identity, Base):
    __tablename__ = "exam_plans"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    start_week: Mapped[int] = mapped_column(Integer)
    end_week: Mapped[int] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
