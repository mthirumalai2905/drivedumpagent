"""Persistence helpers. Callers pass an open session and commit it."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.time import utcnow
from backend.database.models import (
    Attachment,
    Email,
    EmailStatus,
    LogStatus,
    ProcessingLog,
    UploadStatus,
)

TERMINAL_EMAIL_STATUSES = {
    EmailStatus.IGNORED,
    EmailStatus.SKIPPED,
    EmailStatus.COMPLETED,
}
MAX_UPLOAD_ATTEMPTS = 5
STALE_PROCESSING = timedelta(minutes=15)


def get_email_by_gmail_id(session: Session, gmail_message_id: str) -> Email | None:
    return session.scalar(
        select(Email).where(Email.gmail_message_id == gmail_message_id)
    )


def should_reprocess(session: Session, email: Email) -> bool:
    if email.processing_status in TERMINAL_EMAIL_STATUSES:
        return False
    if email.processing_status == EmailStatus.PROCESSING:
        updated = email.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=utcnow().tzinfo)
        return updated < utcnow() - STALE_PROCESSING
    if email.processing_status == EmailStatus.FAILED:
        attachments = session.scalars(
            select(Attachment).where(Attachment.email_id == email.id)
        ).all()
        if not attachments:
            return True
        return any(
            item.retryable and item.attempt_count < MAX_UPLOAD_ATTEMPTS
            for item in attachments
            if item.upload_status != UploadStatus.UPLOADED
        )
    return True


def upsert_email(
    session: Session,
    *,
    gmail_message_id: str,
    sender: str,
    subject: str,
    received_at: datetime,
    trigger_matched: bool,
    processing_status: str,
    ai_summary: str | None = None,
) -> Email:
    existing = get_email_by_gmail_id(session, gmail_message_id)
    if existing is None:
        existing = Email(
            gmail_message_id=gmail_message_id,
            sender=sender[:512],
            subject=subject[:998],
            received_at=received_at,
            trigger_matched=trigger_matched,
            processing_status=processing_status,
            ai_summary=ai_summary,
        )
        session.add(existing)
        session.flush()
        return existing

    existing.sender = sender[:512]
    existing.subject = subject[:998]
    existing.received_at = received_at
    existing.trigger_matched = trigger_matched
    existing.processing_status = processing_status
    existing.updated_at = utcnow()
    if ai_summary is not None:
        existing.ai_summary = ai_summary
    session.flush()
    return existing


def get_attachment(
    session: Session, *, email_id: int, gmail_attachment_id: str
) -> Attachment | None:
    return session.scalar(
        select(Attachment).where(
            Attachment.email_id == email_id,
            Attachment.gmail_attachment_id == gmail_attachment_id,
        )
    )


def create_or_get_attachment(
    session: Session,
    *,
    email_id: int,
    original_filename: str,
    sanitized_filename: str,
    mime_type: str,
    file_size: int,
    gmail_attachment_id: str,
    upload_status: str,
    error_message: str | None = None,
    retryable: bool = False,
) -> Attachment:
    existing = get_attachment(
        session, email_id=email_id, gmail_attachment_id=gmail_attachment_id
    )
    if existing is not None:
        return existing
    row = Attachment(
        email_id=email_id,
        original_filename=original_filename[:512],
        sanitized_filename=sanitized_filename[:255],
        mime_type=mime_type[:255],
        file_size=file_size,
        gmail_attachment_id=gmail_attachment_id[:1024],
        upload_status=upload_status,
        error_message=error_message,
        retryable=retryable,
    )
    session.add(row)
    session.flush()
    return row


def add_log(
    session: Session,
    *,
    event_type: str,
    status: str,
    message: str,
    email_id: int | None = None,
    attachment_id: int | None = None,
) -> None:
    session.add(
        ProcessingLog(
            email_id=email_id,
            attachment_id=attachment_id,
            event_type=event_type[:64],
            status=status[:32],
            message=message[:2000],
        )
    )
    session.flush()


def reset_failed_attachments(session: Session) -> int:
    rows = session.scalars(
        select(Attachment).where(
            Attachment.upload_status.in_([UploadStatus.FAILED, UploadStatus.SKIPPED])
        )
    ).all()
    email_ids = set()
    for row in rows:
        if row.upload_status == UploadStatus.UPLOADED:
            continue
        row.upload_status = UploadStatus.PENDING
        row.retryable = True
        row.attempt_count = 0
        row.error_message = None
        row.updated_at = utcnow()
        email_ids.add(row.email_id)
    if email_ids:
        emails = session.scalars(select(Email).where(Email.id.in_(email_ids))).all()
        for email in emails:
            email.processing_status = EmailStatus.PENDING
            email.updated_at = utcnow()
    session.flush()
    return len(rows)


def processing_stats(session: Session) -> dict[str, int]:
    emails_scanned = session.scalar(select(func.count()).select_from(Email)) or 0
    trigger_matches = (
        session.scalar(
            select(func.count()).select_from(Email).where(Email.trigger_matched.is_(True))
        )
        or 0
    )
    attachments_detected = session.scalar(select(func.count()).select_from(Attachment)) or 0
    uploads_succeeded = (
        session.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.upload_status == UploadStatus.UPLOADED)
        )
        or 0
    )
    uploads_failed = (
        session.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.upload_status == UploadStatus.FAILED)
        )
        or 0
    )
    pending = (
        session.scalar(
            select(func.count())
            .select_from(Email)
            .where(
                Email.processing_status.in_(
                    [EmailStatus.PENDING, EmailStatus.PROCESSING]
                )
            )
        )
        or 0
    )
    return {
        "emails_scanned": int(emails_scanned),
        "trigger_matches": int(trigger_matches),
        "attachments_detected": int(attachments_detected),
        "uploads_succeeded": int(uploads_succeeded),
        "uploads_failed": int(uploads_failed),
        "pending": int(pending),
    }


def list_emails(session: Session, *, limit: int, offset: int) -> tuple[list[Email], int]:
    total = session.scalar(select(func.count()).select_from(Email)) or 0
    rows = session.scalars(
        select(Email).order_by(Email.received_at.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), int(total)


def list_attachments(
    session: Session, *, limit: int, offset: int
) -> tuple[list[Attachment], int]:
    total = session.scalar(select(func.count()).select_from(Attachment)) or 0
    rows = session.scalars(
        select(Attachment)
        .order_by(Attachment.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), int(total)


def list_logs(
    session: Session,
    *,
    limit: int,
    offset: int,
    status: str | None,
) -> tuple[list[tuple[ProcessingLog, Email | None, Attachment | None]], int]:
    filters = []
    if status == "success":
        filters.append(ProcessingLog.status == LogStatus.SUCCESS)
    elif status == "failed":
        filters.append(ProcessingLog.status == LogStatus.FAILED)
    elif status == "pending":
        filters.append(ProcessingLog.status == LogStatus.PENDING)

    count_stmt = select(func.count()).select_from(ProcessingLog)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = session.scalar(count_stmt) or 0

    stmt = (
        select(ProcessingLog, Email, Attachment)
        .join(Email, ProcessingLog.email_id == Email.id, isouter=True)
        .join(Attachment, ProcessingLog.attachment_id == Attachment.id, isouter=True)
        .order_by(ProcessingLog.created_at.desc(), ProcessingLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        stmt = stmt.where(*filters)
    rows = session.execute(stmt).all()
    return [(row[0], row[1], row[2]) for row in rows], int(total)
