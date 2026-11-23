import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, event, func, text
from sqlalchemy.ext.hybrid import hybrid_property
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
    # Large payloads (reports reach several MB); load only on attribute access
    # so metadata checks do not ship them over the shared database link.
    extracted_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    concept_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(50))
    extraction_report: Mapped[dict | None] = mapped_column(JSON, deferred=True)


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


class ModelCall(Identity, Base):
    """Only model I/O crosses the worker boundary; all application writes stay in the API."""
    __tablename__ = "model_calls"
    __table_args__ = (Index("uq_model_call", "job_id", "generation", "fingerprint", unique=True),)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(50))


class GeminiQuota(Base):
    """Server-only shared pacing; no credentials, prompts or student data."""
    __tablename__ = "gemini_quotas"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_at: Mapped[float] = mapped_column(Float, default=0)
    active_until: Mapped[float] = mapped_column(Float, default=0)
    active_token: Mapped[str | None] = mapped_column(String(36))
    active_leases: Mapped[dict | None] = mapped_column(JSON)
    blocked_until: Mapped[float] = mapped_column(Float, default=0)
    blocked_code: Mapped[str | None] = mapped_column(String(50))
    recent: Mapped[list] = mapped_column(JSON, default=list)
    day: Mapped[str] = mapped_column(String(10), default="")
    day_count: Mapped[int] = mapped_column(Integer, default=0)


class GeminiPaidCallBudget(Base):
    """Durable admission count for one operator-limited material version."""
    __tablename__ = "gemini_paid_call_budgets"
    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[int] = mapped_column(Integer, default=0)


class AIWorker(Base):
    __tablename__ = "ai_workers"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    models_ready: Mapped[bool] = mapped_column(Boolean, default=False)


class CodeRun(Identity, Base):
    __tablename__ = "code_runs"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), index=True)
    language: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodeWorker(Base):
    __tablename__ = "code_workers"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready: Mapped[bool] = mapped_column(Boolean, default=False)


class UploadIntent(Identity, Base):
    __tablename__ = "upload_intents"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id"))
    object_key: Mapped[str] = mapped_column(String(100), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)


class ChatMessage(Identity, Base):
    __tablename__ = "chat_messages"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    learning_context: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[dict | None] = mapped_column(JSON)
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


class ContentGeneration(Identity, Base):
    __tablename__ = "content_generations"
    __table_args__ = (
        Index("uq_week_content_draft", "course_id", "week", unique=True,
              postgresql_where=text("status = 'draft'"), sqlite_where=text("status = 'draft'")),
        Index("uq_week_content_published", "course_id", "week", unique=True,
              postgresql_where=text("status = 'published'"), sqlite_where=text("status = 'published'")),
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    week: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    source_hash: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSON)
    concept_ids: Mapped[list] = mapped_column(JSON, default=list)
    concept_evidence: Mapped[list] = mapped_column(JSON, default=list)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    student_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey("material_versions.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20), default="bank")
    generation_id: Mapped[str | None] = mapped_column(ForeignKey("content_generations.id"), index=True)


class DailyPlan(Identity, Base):
    __tablename__ = "daily_plans"
    __table_args__ = (Index("uq_plan_student_section_day", "student_id", "section_id", "day", unique=True),)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    week: Mapped[int] = mapped_column(Integer)
    day_index: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    context: Mapped[dict] = mapped_column(JSON)


class ConceptVideo(Identity, Base):
    __tablename__ = "concept_videos"
    __table_args__ = (Index("uq_video_generation_concept", "generation_id", "concept_id", unique=True),)
    generation_id: Mapped[str | None] = mapped_column(ForeignKey("content_generations.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("material_versions.id"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="script_pending", index=True)
    script_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    script: Mapped[dict | None] = mapped_column(JSON)
    request: Mapped[dict | None] = mapped_column(JSON)
    provider_session_id: Mapped[str | None] = mapped_column(String(150))
    provider_video_id: Mapped[str | None] = mapped_column(String(150))
    object_key: Mapped[str | None] = mapped_column(String(300))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(80))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PracticeExercise(Identity, Base):
    __tablename__ = "practice_exercises"
    __table_args__ = (Index("uq_exercise_generation_key", "generation_id", "source_key", "kind", unique=True),)
    generation_id: Mapped[str | None] = mapped_column(ForeignKey("content_generations.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("material_versions.id"), index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(Text)
    blanks: Mapped[dict] = mapped_column(JSON, default=dict)
    tests: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    @hybrid_property
    def problem_id(self):
        """Both variants of a published source share an ID; unlinked legacy rows stand alone."""
        return f"{self.generation_id}:{self.source_key}" if self.generation_id is not None else self.id

    @problem_id.inplace.expression
    @classmethod
    def _problem_id_expression(cls):
        return func.coalesce(cls.generation_id + ":" + cls.source_key, cls.id)


class PracticeSession(Identity, Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (
        Index("uq_practice_student_section_day", "student_id", "section_id", "day", unique=True),
        Index("uq_weekly_practice_archive", "student_id", "section_id", "week", unique=True,
              postgresql_where=text("day IS NULL")),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), index=True)
    day: Mapped[date | None] = mapped_column(Date)
    week: Mapped[int] = mapped_column(Integer)
    exercise_ids: Mapped[list] = mapped_column(JSON)


class PracticeAttempt(Identity, Base):
    __tablename__ = "practice_attempts"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("practice_exercises.id"), index=True)
    practice_session_id: Mapped[str] = mapped_column(ForeignKey("practice_sessions.id"), index=True)
    source: Mapped[str] = mapped_column(Text)
    submission_snapshot: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    correct: Mapped[bool | None] = mapped_column(Boolean)
    independent: Mapped[bool] = mapped_column(Boolean, default=True)
    feedback: Mapped[dict | None] = mapped_column(JSON)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))


class LearningSession(Identity, Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        Index("uq_daily_student_section", "student_id", "section_id", "day", unique=True,
              postgresql_where=text("archive_week IS NULL"), sqlite_where=text("archive_week IS NULL")),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    day: Mapped[date] = mapped_column(Date)
    question_ids: Mapped[list] = mapped_column(JSON)
    archive_week: Mapped[int | None] = mapped_column(Integer)
    archive_day_index: Mapped[int | None] = mapped_column(Integer)


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


class TheoryRetake(Identity, Base):
    __tablename__ = "theory_retakes"
    original_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    score: Mapped[int | None] = mapped_column(Integer)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[dict | None] = mapped_column(JSON)


def grading_attempt(session, job):
    model = TheoryRetake if job.payload.get("retake") else Attempt
    return session.get(model, job.payload["attempt_id"])


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


@event.listens_for(Job, "before_insert")
def stamp_job_provider(_mapper, _connection, job):
    """Freeze the selected provider at enqueue time; legacy pending jobs stay on Ollama."""
    from lerny.config import settings

    if job.kind in {"extract", "embed", "chat", "questions", "grade", "auto_concepts", "weekly_content",
                    "lecture_grounding", "rag_reindex", "narration_lesson", "daily_theory",
                    "practice_prepare", "practice_grade"}:
        job.payload = {**(job.payload or {}), "_ai_provider": settings().ai_provider}


class GoogleSlidesConnection(Base):
    __tablename__ = "google_slides_connections"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    refresh_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GoogleSlidesServiceConnection(Base):
    __tablename__ = "google_slides_service_connections"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    refresh_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GoogleSlidesOAuthState(Base):
    __tablename__ = "google_slides_oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
