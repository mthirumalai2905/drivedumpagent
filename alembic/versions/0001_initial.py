"""Initial Back Office schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gmail_message_id", sa.String(length=128), nullable=False),
        sa.Column("sender", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_matched", sa.Boolean(), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gmail_message_id", name="uq_emails_gmail_message_id"),
    )
    op.create_index("ix_emails_processing_status", "emails", ["processing_status"])
    op.create_index("ix_emails_received_at", "emails", ["received_at"])

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("sanitized_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("gmail_attachment_id", sa.String(length=1024), nullable=False),
        sa.Column("google_drive_file_id", sa.String(length=128), nullable=True),
        sa.Column("upload_status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("ai_description", sa.Text(), nullable=True),
        sa.Column("ai_category", sa.String(length=80), nullable=True),
        sa.Column("ai_attachment_type", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "email_id",
            "gmail_attachment_id",
            name="uq_attachments_email_gmail_attachment",
        ),
    )
    op.create_index("ix_attachments_email_id", "attachments", ["email_id"])
    op.create_index("ix_attachments_upload_status", "attachments", ["upload_status"])

    op.create_table(
        "processing_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_id", sa.Integer(), nullable=True),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_processing_logs_created_at", "processing_logs", ["created_at"])
    op.create_index("ix_processing_logs_status", "processing_logs", ["status"])
    op.create_index("ix_processing_logs_email_id", "processing_logs", ["email_id"])

    op.create_table(
        "worker_locks",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_locks")
    op.drop_table("processing_logs")
    op.drop_table("attachments")
    op.drop_table("emails")
