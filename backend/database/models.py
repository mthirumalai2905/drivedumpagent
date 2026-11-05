"""SQLAlchemy models for email processing records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.core.time import utcnow


class Base(DeclarativeBase):
    pass


class EmailStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"
    SKIPPED = "skipped"


class UploadStatus:
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    SKIPPED = "skipped"


class LogStatus:
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    SKIPPED = "skipped"


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        Index("ix_emails_processing_status", "processing_status"),
        Index("ix_emails_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    sender: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger_matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )
    logs: Mapped[list["ProcessingLog"]] = relationship(back_populates="email")


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "email_id",
            "gmail_attachment_id",
            name="uq_attachments_email_gmail_attachment",
        ),
        Index("ix_attachments_email_id", "email_id"),
        Index("ix_attachments_upload_status", "upload_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sanitized_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gmail_attachment_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    google_drive_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_attachment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    email: Mapped[Email] = relationship(back_populates="attachments")
    logs: Mapped[list["ProcessingLog"]] = relationship(back_populates="attachment")


class ProcessingLog(Base):
    __tablename__ = "processing_logs"
    __table_args__ = (
        Index("ix_processing_logs_created_at", "created_at"),
        Index("ix_processing_logs_status", "status"),
        Index("ix_processing_logs_email_id", "email_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[int | None] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=True
    )
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    email: Mapped[Email | None] = relationship(back_populates="logs")
    attachment: Mapped[Attachment | None] = relationship(back_populates="logs")


class WorkerLock(Base):
    __tablename__ = "worker_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
