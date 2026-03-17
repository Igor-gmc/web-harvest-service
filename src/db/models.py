from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import CheckpointStep, ErrorType, ProxyStatus, TaskStatus, TaskType
from src.db.base import Base


class ParseTask(Base):
    """Очередь задач и состояние обработки."""

    __tablename__ = "parse_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_value: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TaskStatus.pending
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assigned_proxy_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proxy_configs.id", ondelete="SET NULL"), nullable=True
    )
    worker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    checkpoint_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    fedresurs_results: Mapped[list["FedresursResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    kad_arbitr_results: Mapped[list["KadArbitrResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("task_type", "source_value", name="uq_parse_tasks_type_value"),
        Index("ix_parse_tasks_status", "status"),
        Index("ix_parse_tasks_task_type", "task_type"),
        Index("ix_parse_tasks_next_retry_at", "next_retry_at"),
        Index("ix_parse_tasks_assigned_proxy_id", "assigned_proxy_id"),
        Index("ix_parse_tasks_lock_expires_at", "lock_expires_at"),
    )


class FedresursResult(Base):
    """Результаты парсинга fedresurs.ru."""

    __tablename__ = "fedresurs_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("parse_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    inn: Mapped[str] = mapped_column(String(12), nullable=False)
    case_number: Mapped[str] = mapped_column(String(256), nullable=False)
    last_publication_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["ParseTask"] = relationship(back_populates="fedresurs_results")

    __table_args__ = (
        UniqueConstraint(
            "inn",
            "case_number",
            "last_publication_date",
            name="uq_fedresurs_results_inn_case_date",
        ),
    )


class KadArbitrResult(Base):
    """Результаты парсинга kad.arbitr.ru."""

    __tablename__ = "kad_arbitr_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("parse_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_number: Mapped[str] = mapped_column(String(256), nullable=False)
    document_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["ParseTask"] = relationship(back_populates="kad_arbitr_results")

    __table_args__ = (
        UniqueConstraint(
            "case_number",
            "document_date",
            "document_name",
            name="uq_kad_arbitr_results_case_date_doc",
        ),
    )


class ProxyConfig(Base):
    """Конфигурация и статистика прокси."""

    __tablename__ = "proxy_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password: Mapped[str | None] = mapped_column(String(256), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProxyStatus.active
    )
    max_concurrent_tasks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captcha_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TaskEvent(Base):
    """История ключевых событий по задаче."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("parse_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["ParseTask"] = relationship(back_populates="events")

    __table_args__ = (Index("ix_task_events_task_id", "task_id"),)
