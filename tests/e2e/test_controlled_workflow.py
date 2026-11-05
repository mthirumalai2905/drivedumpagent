"""Controlled workflow with fake Gmail and Drive. No live credentials are used."""

import pytest

from app.database.models import EmailStatus, UploadStatus
from app.database.session import session_scope
from sqlalchemy import select
from app.database.models import Attachment, Email
from tests.integration.test_pipeline import _factory, _pdf, _processor
from tests.fakes import FakeDeepSeek, FakeDrive, FakeGmail, gmail_message


@pytest.mark.asyncio
async def test_controlled_back_office_workflow(tmp_path):
    factory = _factory(tmp_path)
    invoice = gmail_message(
        "live-1",
        "Back Office - November Invoice",
        "Please find the invoice attached.",
        [("invoice.pdf", "application/pdf", "att-live", 32)],
    )
    ignored = gmail_message("live-2", "Personal Conversation", "Nothing to file.", [])
    empty = gmail_message("live-3", "Back Office", "Keyword matched, no file.", [])
    gmail = FakeGmail(
        {"live-1": invoice, "live-2": ignored, "live-3": empty},
        {("live-1", "att-live"): _pdf()},
    )
    drive = FakeDrive()
    processor = _processor(factory, gmail, drive, FakeDeepSeek())

    first = await processor.run_cycle()
    assert first.uploaded == 1
    assert len(drive.uploads) == 1

    second = await _processor(factory, gmail, drive, FakeDeepSeek()).run_cycle()
    assert second.uploaded == 0
    assert len(drive.uploads) == 1

    with session_scope(factory) as session:
        rows = {row.gmail_message_id: row for row in session.scalars(select(Email)).all()}
        attachment = session.scalar(select(Attachment))
    assert rows["live-1"].processing_status == EmailStatus.COMPLETED
    assert rows["live-1"].trigger_matched is True
    assert rows["live-2"].processing_status == EmailStatus.IGNORED
    assert rows["live-3"].processing_status == EmailStatus.SKIPPED
    assert attachment.upload_status == UploadStatus.UPLOADED
    assert attachment.google_drive_file_id == "drive-1"
