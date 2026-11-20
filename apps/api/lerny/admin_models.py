"""Server-only administration state; never exposed through the browser Data API."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lerny.models import Base, Identity, now


class AdminGrant(Base):
    __tablename__ = "admin_grants"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="operator")
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    pending_secret: Mapped[str | None] = mapped_column(Text)
    pending_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_counter: Mapped[int] = mapped_column(Integer, default=-1)
    recovery_hashes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AdminProof(Base):
    __tablename__ = "admin_proofs"
    session_id: Mapped[str] = mapped_column(
        ForeignKey("login_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OperationsState(Base):
    __tablename__ = "operations_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(
        String(500), default="현재 서비스 점검 중입니다. 잠시 후 다시 이용해 주세요."
    )
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    server_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduler_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationsWorker(Base):
    __tablename__ = "operations_workers"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    server_id: Mapped[str | None] = mapped_column(String(30))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ready: Mapped[bool] = mapped_column(Boolean, default=True)
    busy: Mapped[bool] = mapped_column(Boolean, default=False)


class ServerCommand(Identity, Base):
    __tablename__ = "server_commands"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
