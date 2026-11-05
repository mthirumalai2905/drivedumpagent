"""Gmail to Drive processing pipeline."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import Settings
from backend.core.errors import GoogleAuthError, IntegrationError
from backend.core.logging import log_event
from backend.core.redaction import redact
from backend.core.time import utcnow
from backend.database import locks, repository
from backend.database.models import Attachment, EmailStatus, LogStatus, UploadStatus
from backend.database.session import session_scope
from backend.integrations.deepseek import AttachmentInsight, DeepSeekClient
from backend.integrations.gmail import GmailClient
from backend.services.attachment_processor import normalize_mime, sanitize_filename, validate_attachment
from backend.services.content_reader import read_excerpt
from backend.services.email_parser import ParsedAttachment, ParsedEmail, parse_gmail_message
from backend.services.file_classifier import classify_file, folder_for
from backend.services.trigger_engine import message_matches
from backend.services.upload_service import UploadService

LOCK_NAME = "gmail_poller"


def redact_message(exc: Exception) -> str:
    text = redact(str(exc)).replace("\n", " ")
    return text[:300] or "Message processing failed"


def _intent_label(insight: AttachmentInsight | None) -> str:
    if insight is None or not insight.category:
        return ""
    label = "".join(char for char in insight.category if char.isprintable() and char not in "\r\n\t")
    return label.strip()[:80]


@dataclass
class CycleResult:
    discovered: int = 0
    matched: int = 0
    uploaded: int = 0
    failed: int = 0
    skipped: int = 0
    locked: bool = False
    detail: str = ""


class EmailProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        gmail: GmailClient | None,
        uploads: UploadService | None,
        deepseek: DeepSeekClient | None,
        lock_owner: str,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._gmail = gmail
        self._uploads = uploads
        self._deepseek = deepseek
        self._lock_owner = lock_owner
        self._ai_cooldown_until = 0.0

    async def run_cycle(self, *, reprocess_failed: bool = False) -> CycleResult:
        if self._gmail is None or self._uploads is None:
            log_event(
                logging.WARNING,
                "poll_skipped",
                "Gmail polling skipped because Google credentials are not configured",
                status="skipped",
            )
            return CycleResult(detail="google_not_configured")

        with session_scope(self._session_factory) as session:
            acquired = locks.acquire_worker_lock(
                session,
                name=LOCK_NAME,
                owner=self._lock_owner,
                ttl_seconds=self._settings.lock_ttl_seconds,
            )
        if not acquired:
            log_event(
                logging.INFO,
                "poll_locked",
                "Skipped polling because another worker holds the lock",
                status="skipped",
            )
            return CycleResult(locked=True, detail="locked")

        result = CycleResult()
        try:
            if reprocess_failed:
                with session_scope(self._session_factory) as session:
                    reset = repository.reset_failed_attachments(session)
                log_event(
                    logging.INFO,
                    "retry",
                    f"Reset {reset} failed or skipped attachments for another attempt",
                    status="pending",
                )
            try:
                profile = await self._gmail.get_profile_email()
            except GoogleAuthError:
                raise
            except IntegrationError as exc:
                log_event(logging.ERROR, "gmail_auth", str(exc), status="failed")
                result.detail = "gmail_unreachable"
                return result

            expected = self._settings.google_gmail_user.lower()
            if expected and profile.lower() != expected:
                message = "Connected Gmail account does not match GOOGLE_GMAIL_USER"
                log_event(logging.ERROR, "gmail_auth", message, status="failed")
                result.detail = "gmail_account_mismatch"
                return result

            log_event(logging.INFO, "gmail_auth", "Gmail authentication succeeded", status="success")
            log_event(logging.INFO, "gmail_poll", "Polling Gmail", status="pending")
            message_ids = await self._gmail.list_message_ids(
                lookback_minutes=self._settings.email_lookback_minutes,
                limit=self._settings.max_messages_per_cycle,
            )
            result.discovered = len(message_ids)
            log_event(
                logging.INFO,
                "emails_discovered",
                f"Discovered {len(message_ids)} recent messages",
                status="success",
            )
            for message_id in message_ids:
                try:
                    outcome = await self.process_message(message_id)
                except GoogleAuthError:
                    raise
                except Exception as exc:
                    result.failed += 1
                    log_event(
                        logging.ERROR,
                        "email_failed",
                        redact_message(exc),
                        status="failed",
                        email_id=message_id,
                        error_type=type(exc).__name__,
                    )
                    continue
                result.matched += outcome.matched
                result.uploaded += outcome.uploaded
                result.failed += outcome.failed
                result.skipped += outcome.skipped
            result.detail = "completed"
            log_event(
                logging.INFO,
                "poll_completed",
                "Polling cycle completed",
                status="success",
                discovered=result.discovered,
                uploaded=result.uploaded,
                failed=result.failed,
            )
            return result
        finally:
            with session_scope(self._session_factory) as session:
                locks.release_worker_lock(
                    session, name=LOCK_NAME, owner=self._lock_owner
                )

    async def process_message(self, message_id: str) -> CycleResult:
        revisit_id: int | None = None
        with session_scope(self._session_factory) as session:
            existing = repository.get_email_by_gmail_id(session, message_id)
            if existing is not None and not repository.should_reprocess(session, existing):
                if existing.processing_status == EmailStatus.IGNORED:
                    return CycleResult(skipped=1)
                revisit_id = existing.id
        if revisit_id is not None and not self._skipped_attachment_now_allowed(revisit_id):
            return CycleResult(skipped=1)

        assert self._gmail is not None
        raw = await self._gmail.get_message(message_id)
        parsed = parse_gmail_message(raw)
        if not parsed.gmail_message_id:
            parsed.gmail_message_id = message_id
        keyword = message_matches(
            parsed.subject, parsed.body, self._settings.keywords
        )
        if keyword is None:
            self._save_email(parsed, trigger_matched=False, status=EmailStatus.IGNORED, summary=None)
            log_event(
                logging.INFO,
                "trigger_missed",
                "Email did not match the trigger keyword",
                status="skipped",
                email_id=message_id,
            )
            return CycleResult(skipped=1)

        if not parsed.attachments:
            email_id = self._save_email(
                parsed, trigger_matched=True, status=EmailStatus.SKIPPED, summary=None
            )
            self._log_db(
                event_type="trigger_matched",
                status=LogStatus.SKIPPED,
                message="Keyword matched but the email has no attachments",
                email_id=email_id,
                gmail_id=message_id,
            )
            return CycleResult(matched=1, skipped=1)

        email_id = self._save_email(
            parsed, trigger_matched=True, status=EmailStatus.PROCESSING, summary=None
        )
        self._log_db(
            event_type="trigger_matched",
            status=LogStatus.SUCCESS,
            message=f"Keyword matched: {keyword}",
            email_id=email_id,
            gmail_id=message_id,
        )
        insight = await self._maybe_inspect(parsed)
        if insight and insight.summary:
            self._save_email(
                parsed,
                trigger_matched=True,
                status=EmailStatus.PROCESSING,
                summary=insight.summary[:1000],
            )

        uploaded = 0
        failed = 0
        skipped = 0
        insights = {
            item.filename: item for item in (insight.attachments if insight else [])
        }
        log_event(
            logging.INFO,
            "attachments_discovered",
            f"Found {len(parsed.attachments)} attachments",
            status="success",
            email_id=parsed.gmail_message_id,
        )
        limited = parsed.attachments[: self._settings.max_attachments_per_email]
        for part in parsed.attachments[self._settings.max_attachments_per_email :]:
            self._store_rejection(
                email_id,
                parsed,
                part,
                sanitize_filename(part.filename),
                "attachment limit exceeded",
            )
            skipped += 1
        for part in limited:
            outcome = await self._process_attachment(
                email_pk=email_id,
                parsed=parsed,
                part=part,
                insight=insights.get(part.filename),
            )
            uploaded += outcome.uploaded
            failed += outcome.failed
            skipped += outcome.skipped

        if failed:
            final_status = EmailStatus.FAILED
        elif uploaded:
            final_status = EmailStatus.COMPLETED
        else:
            final_status = EmailStatus.SKIPPED
        self._save_email(
            parsed,
            trigger_matched=True,
            status=final_status,
            summary=insight.summary[:1000] if insight else None,
        )
        return CycleResult(matched=1, uploaded=uploaded, failed=failed, skipped=skipped)

    async def _process_attachment(
        self,
        *,
        email_pk: int,
        parsed: ParsedEmail,
        part: ParsedAttachment,
        insight: AttachmentInsight | None,
    ) -> CycleResult:
        validation = validate_attachment(
            filename=part.filename,
            mime_type=part.mime_type,
            size=part.size,
            allowed_mimes=self._settings.mime_allowlist,
            max_bytes=self._settings.max_attachment_bytes,
        )
        if not validation.ok:
            self._store_rejection(email_pk, parsed, part, validation.filename, validation.reason or "rejected")
            return CycleResult(skipped=1)

        with session_scope(self._session_factory) as session:
            existing = repository.get_attachment(
                session, email_id=email_pk, gmail_attachment_id=part.attachment_id
            )
            if existing and existing.upload_status == UploadStatus.UPLOADED:
                return CycleResult(skipped=1)
            if (
                existing
                and existing.upload_status == UploadStatus.FAILED
                and not existing.retryable
            ):
                return CycleResult(skipped=1)
            if (
                existing
                and existing.upload_status == UploadStatus.FAILED
                and existing.attempt_count >= repository.MAX_UPLOAD_ATTEMPTS
            ):
                return CycleResult(failed=1)

        try:
            data = part.data if part.data is not None else await self._gmail.get_attachment(  # type: ignore[union-attr]
                parsed.gmail_message_id, part.attachment_id
            )
        except IntegrationError as exc:
            self._store_failure(
                email_pk,
                parsed,
                part,
                validation.filename,
                str(exc),
                retryable=exc.retryable,
            )
            return CycleResult(failed=1)

        if not data or len(data) > self._settings.max_attachment_bytes:
            reason = "attachment is empty" if not data else "attachment exceeds size limit"
            self._store_rejection(email_pk, parsed, part, validation.filename, reason)
            return CycleResult(skipped=1)

        part.size = len(data)
        digest = hashlib.sha256(data).hexdigest()
        mime = normalize_mime(part.mime_type)
        kind = classify_file(validation.filename, mime, data)
        folder_name = folder_for(kind)
        prior = self._existing_drive_file(validation.filename, digest)
        if prior:
            self._store_success(
                email_pk,
                parsed,
                part,
                validation.filename,
                mime,
                digest,
                prior,
                duplicate=True,
                insight=insight,
                folder_name=folder_name,
            )
            return CycleResult(uploaded=1)
        excerpt = read_excerpt(data, kind)
        content_insight = await self._describe_file(part, mime, excerpt)
        if content_insight is not None:
            insight = content_insight
        assert self._uploads is not None
        try:
            uploaded = await self._uploads.upload_bytes(
                message_id=parsed.gmail_message_id,
                attachment_id=part.attachment_id,
                filename=validation.filename,
                mime_type=mime,
                data=data,
                folder_name=folder_name,
            )
        except IntegrationError as exc:
            self._store_failure(
                email_pk,
                parsed,
                part,
                validation.filename,
                str(exc),
                retryable=exc.retryable,
                digest=digest,
                size=len(data),
            )
            return CycleResult(failed=1)
        finally:
            del data

        self._store_success(
            email_pk,
            parsed,
            part,
            validation.filename,
            mime,
            digest,
            uploaded.file_id,
            duplicate=uploaded.duplicate,
            insight=insight,
            folder_name=uploaded.folder_name,
        )
        return CycleResult(uploaded=1)

    def _skipped_attachment_now_allowed(self, email_pk: int) -> bool:
        with session_scope(self._session_factory) as session:
            rows = session.scalars(
                select(Attachment).where(
                    Attachment.email_id == email_pk,
                    Attachment.upload_status == UploadStatus.SKIPPED,
                )
            ).all()
            for row in rows:
                verdict = validate_attachment(
                    filename=row.sanitized_filename,
                    mime_type=row.mime_type,
                    size=row.file_size,
                    allowed_mimes=self._settings.mime_allowlist,
                    max_bytes=self._settings.max_attachment_bytes,
                )
                if verdict.ok:
                    return True
        return False

    def _existing_drive_file(self, filename: str, digest: str) -> str | None:
        with session_scope(self._session_factory) as session:
            file_id = session.scalar(
                select(Attachment.google_drive_file_id)
                .where(
                    Attachment.upload_status == UploadStatus.UPLOADED,
                    Attachment.google_drive_file_id.is_not(None),
                    Attachment.google_drive_file_id != "",
                    or_(
                        Attachment.content_sha256 == digest,
                        Attachment.sanitized_filename == filename,
                    ),
                )
                .order_by(Attachment.id.asc())
                .limit(1)
            )
        return str(file_id) if file_id else None

    async def _describe_file(
        self,
        part: ParsedAttachment,
        mime: str,
        excerpt: str,
    ) -> AttachmentInsight | None:
        if self._deepseek is None or time.time() < self._ai_cooldown_until:
            return None
        if sum(char.isalpha() for char in excerpt) < 20:
            return None
        try:
            return await self._deepseek.describe_document(
                filename=part.filename,
                mime_type=mime,
                excerpt=excerpt,
            )
        except IntegrationError as exc:
            self._ai_cooldown_until = time.time() + 600
            log_event(
                logging.WARNING,
                "deepseek_failed",
                str(exc),
                status="failed",
            )
            return None

    async def _maybe_inspect(self, parsed: ParsedEmail):
        if self._deepseek is None or time.time() < self._ai_cooldown_until:
            return None
        try:
            insight = await self._deepseek.inspect_email(
                subject=parsed.subject,
                sender=parsed.sender,
                body_excerpt=parsed.body[:1200],
                attachments=[
                    (item.filename, item.mime_type, item.size) for item in parsed.attachments
                ],
            )
        except IntegrationError as exc:
            self._ai_cooldown_until = time.time() + 600
            log_event(
                logging.WARNING,
                "deepseek_failed",
                str(exc),
                status="failed",
                email_id=parsed.gmail_message_id,
            )
            return None
        log_event(
            logging.INFO,
            "deepseek_completed",
            "Stored an optional email summary",
            status="success",
            email_id=parsed.gmail_message_id,
        )
        return insight

    def _save_email(
        self,
        parsed: ParsedEmail,
        *,
        trigger_matched: bool,
        status: str,
        summary: str | None,
    ) -> int:
        with session_scope(self._session_factory) as session:
            email = repository.upsert_email(
                session,
                gmail_message_id=parsed.gmail_message_id,
                sender=parsed.sender,
                subject=parsed.subject,
                received_at=parsed.received_at,
                trigger_matched=trigger_matched,
                processing_status=status,
                ai_summary=summary,
            )
            if not trigger_matched:
                repository.add_log(
                    session,
                    event_type="trigger_missed",
                    status=LogStatus.SKIPPED,
                    message="Keyword did not match",
                    email_id=email.id,
                )
            return email.id

    def _log_db(
        self,
        *,
        event_type: str,
        status: str,
        message: str,
        email_id: int | None,
        gmail_id: str,
        attachment_id: int | None = None,
        filename: str | None = None,
    ) -> None:
        level = logging.ERROR if status == LogStatus.FAILED else logging.INFO
        log_event(
            level,
            event_type,
            message,
            status=status,
            email_id=gmail_id,
            filename=filename,
        )
        with session_scope(self._session_factory) as session:
            repository.add_log(
                session,
                event_type=event_type,
                status=status,
                message=message,
                email_id=email_id,
                attachment_id=attachment_id,
            )

    def _store_rejection(
        self,
        email_pk: int,
        parsed: ParsedEmail,
        part: ParsedAttachment,
        filename: str,
        reason: str,
    ) -> None:
        with session_scope(self._session_factory) as session:
            row = repository.create_or_get_attachment(
                session,
                email_id=email_pk,
                original_filename=part.filename,
                sanitized_filename=filename,
                mime_type=normalize_mime(part.mime_type),
                file_size=part.size,
                gmail_attachment_id=part.attachment_id,
                upload_status=UploadStatus.SKIPPED,
                error_message=reason,
                retryable=False,
            )
            if row.upload_status != UploadStatus.UPLOADED:
                row.upload_status = UploadStatus.SKIPPED
                row.error_message = reason
                row.retryable = False
                row.sanitized_filename = filename
                row.updated_at = utcnow()
            repository.add_log(
                session,
                event_type="attachment_rejected",
                status=LogStatus.SKIPPED,
                message=reason,
                email_id=email_pk,
                attachment_id=row.id,
            )
        log_event(
            logging.INFO,
            "attachment_rejected",
            reason,
            status="skipped",
            email_id=parsed.gmail_message_id,
            filename=filename,
        )

    def _store_failure(
        self,
        email_pk: int,
        parsed: ParsedEmail,
        part: ParsedAttachment,
        filename: str,
        reason: str,
        *,
        retryable: bool,
        digest: str | None = None,
        size: int | None = None,
    ) -> None:
        with session_scope(self._session_factory) as session:
            row = repository.create_or_get_attachment(
                session,
                email_id=email_pk,
                original_filename=part.filename,
                sanitized_filename=filename,
                mime_type=normalize_mime(part.mime_type),
                file_size=size if size is not None else part.size,
                gmail_attachment_id=part.attachment_id,
                upload_status=UploadStatus.FAILED,
                error_message=reason[:500],
                retryable=retryable,
            )
            if row.upload_status != UploadStatus.UPLOADED:
                row.upload_status = UploadStatus.FAILED
                row.error_message = reason[:500]
                row.retryable = retryable
                row.attempt_count = row.attempt_count + 1
                row.sanitized_filename = filename
                if digest:
                    row.content_sha256 = digest
                if size is not None:
                    row.file_size = size
                row.updated_at = utcnow()
            repository.add_log(
                session,
                event_type="attachment_upload_failed",
                status=LogStatus.FAILED,
                message=reason[:500],
                email_id=email_pk,
                attachment_id=row.id,
            )
        log_event(
            logging.ERROR,
            "attachment_upload_failed",
            reason[:500],
            status="failed",
            email_id=parsed.gmail_message_id,
            filename=filename,
        )

    def _store_success(
        self,
        email_pk: int,
        parsed: ParsedEmail,
        part: ParsedAttachment,
        filename: str,
        mime: str,
        digest: str,
        file_id: str,
        *,
        duplicate: bool,
        insight: AttachmentInsight | None,
        folder_name: str,
    ) -> None:
        label = _intent_label(insight)
        if duplicate:
            message = "Attachment already existed in Drive"
        elif label:
            message = f"Attachment uploaded to {folder_name} ({label})"
        else:
            message = f"Attachment uploaded to {folder_name}"
        with session_scope(self._session_factory) as session:
            row = repository.create_or_get_attachment(
                session,
                email_id=email_pk,
                original_filename=part.filename,
                sanitized_filename=filename,
                mime_type=mime,
                file_size=part.size,
                gmail_attachment_id=part.attachment_id,
                upload_status=UploadStatus.UPLOADED,
                retryable=False,
            )
            row.upload_status = UploadStatus.UPLOADED
            row.google_drive_file_id = file_id
            row.content_sha256 = digest
            row.error_message = None
            row.retryable = False
            row.sanitized_filename = filename
            row.mime_type = mime
            row.updated_at = utcnow()
            if insight and insight.filename == part.filename:
                row.ai_description = insight.description[:500]
                row.ai_category = insight.category[:80]
                row.ai_attachment_type = insight.attachment_type[:80]
            repository.add_log(
                session,
                event_type="attachment_duplicate" if duplicate else "attachment_uploaded",
                status=LogStatus.SUCCESS,
                message=message,
                email_id=email_pk,
                attachment_id=row.id,
            )
        log_event(
            logging.INFO,
            "attachment_duplicate" if duplicate else "attachment_uploaded",
            message,
            status="success",
            email_id=parsed.gmail_message_id,
            filename=filename,
        )
