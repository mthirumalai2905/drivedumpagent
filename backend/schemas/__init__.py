"""Safe API schemas. These models never include credentials."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    time: datetime


class IntegrationReport(BaseModel):
    state: str
    detail: str


class IntegrationsResponse(BaseModel):
    application: str
    database: IntegrationReport
    gmail: IntegrationReport
    google_drive: IntegrationReport
    deepseek: IntegrationReport
    last_poll_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    poll_running: bool = False


class EmailOut(BaseModel):
    id: int
    gmail_message_id: str
    sender: str
    subject: str
    received_at: datetime
    trigger_matched: bool
    processing_status: str
    ai_summary: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    id: int
    email_id: int
    original_filename: str
    sanitized_filename: str
    mime_type: str
    file_size: int
    gmail_attachment_id: str
    google_drive_file_id: str | None = None
    upload_status: str
    error_message: str | None = None
    attempt_count: int
    ai_description: str | None = None
    ai_category: str | None = None
    ai_attachment_type: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LogOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    status: str
    message: str
    subject: str | None = None
    sender: str | None = None
    filename: str | None = None
    upload_status: str | None = None
    error_message: str | None = None


class Page(BaseModel):
    items: list
    total: int
    limit: int
    offset: int


class StatsOut(BaseModel):
    emails_scanned: int
    trigger_matches: int
    attachments_detected: int
    uploads_succeeded: int
    uploads_failed: int
    pending: int
    last_poll_at: datetime | None = None
    last_success_at: datetime | None = None


class ConfigFlag(BaseModel):
    name: str
    configured: bool


class ConfigStatus(BaseModel):
    app_env: str
    app_name: str
    gmail_user: str
    trigger_keywords: list[str]
    poll_interval_seconds: int
    poll_enabled: bool
    email_lookback_minutes: int
    max_attachment_bytes: int
    database_backend: str
    deepseek_model: str
    deepseek_model_verified: bool | None = None
    flags: list[ConfigFlag]


class RunRequest(BaseModel):
    reprocess_failed: bool = False


class RunResponse(BaseModel):
    discovered: int
    matched: int
    uploaded: int
    failed: int
    skipped: int
    locked: bool
    detail: str


class CreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CreateFolderResponse(BaseModel):
    id: str
    name: str
    detail: str
