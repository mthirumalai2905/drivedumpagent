import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.core.config import get_settings
from backend.database.locks import acquire_worker_lock, release_worker_lock
from backend.database.models import Attachment, Base, Email, EmailStatus, UploadStatus
from backend.database.repository import processing_stats
from backend.database.session import make_engine, make_session_factory, session_scope
from backend.services.email_processor import EmailProcessor
from backend.services.upload_service import UploadService, dedupe_key
from tests.fakes import FakeDeepSeek, FakeDrive, FakeGmail, gmail_message


def _factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'backoffice.db'}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _processor(factory, gmail, drive, deepseek=None):
    settings = get_settings()
    return EmailProcessor(
        settings=settings,
        session_factory=factory,
        gmail=gmail,
        uploads=UploadService(drive, "test-folder"),
        deepseek=deepseek,
        lock_owner="test-worker",
    )


def _pdf(name: str = "invoice.pdf") -> bytes:
    return b"%PDF-1.4 " + name.encode() + b" sample"


@pytest.mark.asyncio
async def test_matching_email_uploads_once_and_restart_does_not_repeat(tmp_path):
    factory = _factory(tmp_path)
    message = gmail_message(
        "msg-1",
        "Back Office - November Invoice",
        "Please find the invoice attached.",
        [("invoice.pdf", "application/pdf", "att-1", 24)],
    )
    gmail = FakeGmail({"msg-1": message}, {("msg-1", "att-1"): _pdf()})
    drive = FakeDrive()
    deepseek = FakeDeepSeek()
    processor = _processor(factory, gmail, drive, deepseek)

    first = await processor.run_cycle()
    assert first.uploaded == 1
    assert drive.uploads[0]["name"] == "invoice.pdf"
    assert drive.uploads[0]["mime_type"] == "application/pdf"
    assert drive.uploads[0]["folder_id"] == "folder-PDFs"
    assert deepseek.calls == 1

    restarted = _processor(factory, gmail, drive, deepseek)
    second = await restarted.run_cycle()
    assert second.uploaded == 0
    assert len(drive.uploads) == 1

    with session_scope(factory) as session:
        email = session.scalar(select(Email).where(Email.gmail_message_id == "msg-1"))
        attachment = session.scalar(select(Attachment).where(Attachment.email_id == email.id))
        stats = processing_stats(session)
    assert email.processing_status == EmailStatus.COMPLETED
    assert email.trigger_matched is True
    assert "invoice" in (email.ai_summary or "").lower()
    assert attachment.google_drive_file_id == "drive-1"
    assert attachment.upload_status == UploadStatus.UPLOADED
    assert stats["uploads_succeeded"] == 1
    assert stats["trigger_matches"] == 1


@pytest.mark.asyncio
async def test_keyword_miss_and_missing_attachment_do_not_upload(tmp_path):
    factory = _factory(tmp_path)
    messages = {
        "msg-a": gmail_message("msg-a", "Personal Conversation", "Hello there.", []),
        "msg-b": gmail_message("msg-b", "Back Office note", "No file here.", []),
    }
    gmail = FakeGmail(messages, {})
    drive = FakeDrive()
    result = await _processor(factory, gmail, drive).run_cycle()
    assert drive.uploads == []
    assert result.uploaded == 0
    with session_scope(factory) as session:
        rows = session.scalars(select(Email)).all()
        statuses = {row.gmail_message_id: row.processing_status for row in rows}
    assert statuses["msg-a"] == EmailStatus.IGNORED
    assert statuses["msg-b"] == EmailStatus.SKIPPED


@pytest.mark.asyncio
async def test_multiple_attachments_and_invalid_mime(tmp_path):
    factory = _factory(tmp_path)
    message = gmail_message(
        "msg-m",
        "Back Office packet",
        "Two files.",
        [
            ("one.pdf", "application/pdf", "att-1", 10),
            ("two.pdf", "application/pdf", "att-2", 10),
            ("../../secret.exe", "application/x-msdownload", "att-3", 10),
        ],
    )
    gmail = FakeGmail(
        {"msg-m": message},
        {
            ("msg-m", "att-1"): _pdf("one"),
            ("msg-m", "att-2"): _pdf("two"),
            ("msg-m", "att-3"): b"MZ-not-run",
        },
    )
    drive = FakeDrive()
    result = await _processor(factory, gmail, drive, FakeDeepSeek()).run_cycle()
    assert result.uploaded == 2
    assert [item["name"] for item in drive.uploads] == ["one.pdf", "two.pdf"]
    assert gmail.downloads == [("msg-m", "att-1"), ("msg-m", "att-2")]
    with session_scope(factory) as session:
        skipped = session.scalar(
            select(Attachment).where(Attachment.gmail_attachment_id == "att-3")
        )
    assert skipped.upload_status == UploadStatus.SKIPPED
    assert skipped.sanitized_filename == "secret.exe"


@pytest.mark.asyncio
async def test_drive_failure_is_not_marked_uploaded_and_can_retry(tmp_path):
    factory = _factory(tmp_path)
    message = gmail_message(
        "msg-f",
        "Back Office",
        "File attached.",
        [("invoice.pdf", "application/pdf", "att-f", 12)],
    )
    gmail = FakeGmail({"msg-f": message}, {("msg-f", "att-f"): _pdf()})
    drive = FakeDrive(fail=True)
    processor = _processor(factory, gmail, drive, FakeDeepSeek(fail=True))
    failed = await processor.run_cycle()
    assert failed.failed == 1
    assert drive.uploads == []
    with session_scope(factory) as session:
        attachment = session.scalar(select(Attachment))
    assert attachment.upload_status == UploadStatus.FAILED
    assert attachment.google_drive_file_id is None
    assert attachment.retryable is True

    drive.fail = False
    retried = await processor.run_cycle()
    assert retried.uploaded == 1
    with session_scope(factory) as session:
        attachment = session.scalar(select(Attachment))
    assert attachment.upload_status == UploadStatus.UPLOADED
    assert attachment.google_drive_file_id == "drive-1"


@pytest.mark.asyncio
async def test_existing_drive_file_is_reused_after_a_lost_database_write(tmp_path):
    factory = _factory(tmp_path)
    message = gmail_message(
        "msg-d",
        "Back Office",
        "File attached.",
        [("invoice.pdf", "application/pdf", "att-d", 12)],
    )
    gmail = FakeGmail({"msg-d": message}, {("msg-d", "att-d"): _pdf()})
    drive = FakeDrive()
    drive.files[dedupe_key("msg-d", "att-d")] = "already-there"
    result = await _processor(factory, gmail, drive).run_cycle()
    assert result.uploaded == 1
    assert drive.uploads == []
    with session_scope(factory) as session:
        attachment = session.scalar(select(Attachment))
    assert attachment.google_drive_file_id == "already-there"


@pytest.mark.asyncio
async def test_content_is_filed_by_type_and_labeled_by_intent(tmp_path):
    factory = _factory(tmp_path)
    sheet = b"vendor,amount,note\nAcme Supplies,1200,quarterly office statement\n"
    picture = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
    message = gmail_message(
        "msg-sort",
        "Back Office packet",
        "Please file these.",
        [
            ("notes.csv", "text/csv", "att-sheet", len(sheet)),
            ("invoice.pdf", "application/pdf", "att-image", len(picture)),
        ],
    )
    gmail = FakeGmail(
        {"msg-sort": message},
        {("msg-sort", "att-sheet"): sheet, ("msg-sort", "att-image"): picture},
    )
    drive = FakeDrive()
    deepseek = FakeDeepSeek()
    result = await _processor(factory, gmail, drive, deepseek).run_cycle()
    assert result.uploaded == 2
    filed = {item["name"]: item["folder_id"] for item in drive.uploads}
    assert filed == {"notes.csv": "folder-Sheets", "invoice.pdf": "folder-Images"}
    assert deepseek.document_calls == 1
    with session_scope(factory) as session:
        rows = {row.sanitized_filename: row for row in session.scalars(select(Attachment)).all()}
    assert rows["notes.csv"].ai_category == "statement"
    assert rows["invoice.pdf"].ai_category == "invoice"


def test_duplicate_gmail_message_is_rejected(tmp_path):
    factory = _factory(tmp_path)
    with session_scope(factory) as session:
        session.add(
            Email(
                gmail_message_id="same",
                sender="a@example.com",
                subject="One",
                received_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                trigger_matched=False,
                processing_status=EmailStatus.IGNORED,
            )
        )
    with pytest.raises(IntegrityError):
        with session_scope(factory) as session:
            session.add(
                Email(
                    gmail_message_id="same",
                    sender="b@example.com",
                    subject="Two",
                    received_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                    trigger_matched=False,
                    processing_status=EmailStatus.IGNORED,
                )
            )


def test_worker_lock_allows_only_one_owner(tmp_path):
    factory = _factory(tmp_path)
    first = factory()
    second = factory()
    try:
        assert acquire_worker_lock(first, name="gmail_poller", owner="a", ttl_seconds=60)
        assert acquire_worker_lock(second, name="gmail_poller", owner="b", ttl_seconds=60) is False
        release_worker_lock(first, name="gmail_poller", owner="a")
        assert acquire_worker_lock(second, name="gmail_poller", owner="b", ttl_seconds=60)
    finally:
        first.close()
        second.close()
