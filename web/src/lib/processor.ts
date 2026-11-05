import { createHash, randomUUID } from "crypto";

import type { Settings } from "./config";
import { describeDocument, inspectEmail, type AttachmentInsight } from "./deepseek";
import { addLog, acquireLock, getDb, nowIso, releaseLock } from "./db";
import { classifyFile, folderFor, readExcerpt, validateAttachment } from "./files";
import { getAttachment, getMessage, listMessageIds, uploadBytes, type IntegrationError } from "./google";
import { parseGmailMessage, type ParsedAttachment, type ParsedEmail } from "./parse";
import { messageMatches } from "./trigger";

export type CycleResult = {
  discovered: number;
  matched: number;
  uploaded: number;
  failed: number;
  skipped: number;
  locked: boolean;
  detail: string;
};

const MAX_ATTEMPTS = 5;

function intentLabel(insight: AttachmentInsight | null): string {
  if (!insight?.category) return "";
  return insight.category.replace(/[\r\n\t]/g, "").trim().slice(0, 80);
}

export async function runCycle(settings: Settings, reprocessFailed = false): Promise<CycleResult> {
  const db = getDb();
  const owner = `next-${randomUUID()}`;
  if (!acquireLock(db, owner, settings.lockTtlSeconds)) {
    return { discovered: 0, matched: 0, uploaded: 0, failed: 0, skipped: 0, locked: true, detail: "locked" };
  }
  try {
    if (!settings.googleRefreshToken || !settings.googleClientId) {
      return { discovered: 0, matched: 0, uploaded: 0, failed: 0, skipped: 0, locked: false, detail: "google_not_configured" };
    }
    const ids = await listMessageIds(settings);
    let matched = 0;
    let uploaded = 0;
    let failed = 0;
    let skipped = 0;
    for (const id of ids) {
      const outcome = await processMessage(settings, id, reprocessFailed);
      matched += outcome.matched;
      uploaded += outcome.uploaded;
      failed += outcome.failed;
      skipped += outcome.skipped;
    }
    return { discovered: ids.length, matched, uploaded, failed, skipped, locked: false, detail: "completed" };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Processing cycle failed";
    addLog(db, "poll_failed", "failed", message.slice(0, 300));
    return { discovered: 0, matched: 0, uploaded: 0, failed: 1, skipped: 0, locked: false, detail: message.slice(0, 300) };
  } finally {
    releaseLock(db, owner);
  }
}

async function processMessage(settings: Settings, messageId: string, reprocessFailed: boolean): Promise<CycleResult> {
  const db = getDb();
  const empty = { discovered: 0, matched: 0, uploaded: 0, failed: 0, skipped: 0, locked: false, detail: "" };
  const existing = db.prepare(`SELECT id, processing_status FROM emails WHERE gmail_message_id = ?`).get(messageId) as
    | { id: number; processing_status: string }
    | undefined;
  if (existing && ["completed", "ignored", "skipped"].includes(existing.processing_status) && !reprocessFailed) {
    return empty;
  }
  const raw = await getMessage(settings, messageId);
  const parsed = parseGmailMessage(raw);
  const keyword = messageMatches(parsed.subject, parsed.body, settings.keywords);
  if (!keyword) {
    saveEmail(parsed, false, "ignored", null);
    addLog(db, "trigger_missed", "skipped", "Keyword was not present", emailId(parsed.gmailMessageId));
    return { ...empty, skipped: 1 };
  }
  const emailPk = saveEmail(parsed, true, "processing", null);
  const insight = await inspectEmail(settings, {
    subject: parsed.subject,
    sender: parsed.sender,
    body: parsed.body,
    attachments: parsed.attachments.map((item) => [item.filename, item.mimeType, item.size]),
  });
  let uploaded = 0;
  let failed = 0;
  let skipped = 0;
  const limited = parsed.attachments.slice(0, settings.maxAttachmentsPerEmail);
  for (const part of parsed.attachments.slice(settings.maxAttachmentsPerEmail)) {
    storeRejection(emailPk, parsed, part, "attachment limit exceeded");
    skipped += 1;
  }
  for (const part of limited) {
    const outcome = await processAttachment(settings, emailPk, parsed, part, insight?.attachments.find((item) => item.filename === part.filename) || null, reprocessFailed);
    uploaded += outcome.uploaded;
    failed += outcome.failed;
    skipped += outcome.skipped;
  }
  const status = failed ? "failed" : uploaded ? "completed" : "skipped";
  saveEmail(parsed, true, status, insight?.summary || null);
  return { ...empty, matched: 1, uploaded, failed, skipped };
}

async function processAttachment(
  settings: Settings,
  emailPk: number,
  parsed: ParsedEmail,
  part: ParsedAttachment,
  insight: AttachmentInsight | null,
  reprocessFailed: boolean,
): Promise<CycleResult> {
  const empty = { discovered: 0, matched: 0, uploaded: 0, failed: 0, skipped: 0, locked: false, detail: "" };
  const validation = validateAttachment({
    filename: part.filename,
    mimeType: part.mimeType,
    size: part.size,
    allowedMimes: settings.allowedMimes,
    maxBytes: settings.maxAttachmentBytes,
  });
  if (!validation.ok) {
    storeRejection(emailPk, parsed, part, validation.reason || "rejected");
    return { ...empty, skipped: 1 };
  }
  const db = getDb();
  const existing = db
    .prepare(`SELECT upload_status, retryable, attempt_count FROM attachments WHERE email_id = ? AND gmail_attachment_id = ?`)
    .get(emailPk, part.attachmentId) as { upload_status: string; retryable: number; attempt_count: number } | undefined;
  if (existing?.upload_status === "uploaded") return { ...empty, skipped: 1 };
  if (existing?.upload_status === "failed" && (!existing.retryable || existing.attempt_count >= MAX_ATTEMPTS) && !reprocessFailed) {
    return { ...empty, skipped: existing.retryable ? 0 : 1, failed: existing.retryable ? 1 : 0 };
  }
  let data: Buffer;
  try {
    data = part.data ?? (await getAttachment(settings, parsed.gmailMessageId, part.attachmentId));
  } catch (error) {
    storeFailure(emailPk, parsed, part, validation.filename, error instanceof Error ? error.message : "download failed", true);
    return { ...empty, failed: 1 };
  }
  if (!data.length || data.length > settings.maxAttachmentBytes) {
    storeRejection(emailPk, parsed, part, data.length ? "attachment exceeds size limit" : "attachment is empty");
    return { ...empty, skipped: 1 };
  }
  const digest = createHash("sha256").update(data).digest("hex");
  const kind = classifyFile(validation.filename, part.mimeType, data);
  const folderName = folderFor(kind);
  const excerpt = await readExcerpt(data, kind);
  const contentInsight = await describeDocument(settings, { filename: part.filename, mimeType: part.mimeType, excerpt });
  const chosen = contentInsight || insight;
  try {
    const uploaded = await uploadBytes({
      settings,
      messageId: parsed.gmailMessageId,
      attachmentId: part.attachmentId,
      filename: validation.filename,
      mimeType: part.mimeType,
      data,
      folderName,
    });
    storeSuccess(emailPk, parsed, part, validation.filename, digest, data.length, uploaded, chosen);
    return { ...empty, uploaded: 1 };
  } catch (error) {
    const integration = error as IntegrationError;
    storeFailure(emailPk, parsed, part, validation.filename, error instanceof Error ? error.message : "upload failed", Boolean(integration.retryable), digest, data.length);
    return { ...empty, failed: 1 };
  }
}

function emailId(gmailMessageId: string): number | null {
  const row = getDb().prepare(`SELECT id FROM emails WHERE gmail_message_id = ?`).get(gmailMessageId) as { id: number } | undefined;
  return row?.id ?? null;
}

function saveEmail(parsed: ParsedEmail, matched: boolean, status: string, summary: string | null): number {
  const db = getDb();
  const now = nowIso();
  const existing = db.prepare(`SELECT id FROM emails WHERE gmail_message_id = ?`).get(parsed.gmailMessageId) as { id: number } | undefined;
  if (existing) {
    db.prepare(
      `UPDATE emails SET sender = ?, subject = ?, received_at = ?, trigger_matched = ?, processing_status = ?, ai_summary = COALESCE(?, ai_summary), updated_at = ? WHERE id = ?`,
    ).run(parsed.sender, parsed.subject, parsed.receivedAt, matched ? 1 : 0, status, summary, now, existing.id);
    return existing.id;
  }
  const result = db.prepare(
    `INSERT INTO emails (gmail_message_id, sender, subject, received_at, trigger_matched, processing_status, ai_summary, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(parsed.gmailMessageId, parsed.sender, parsed.subject, parsed.receivedAt, matched ? 1 : 0, status, summary, now, now);
  return Number(result.lastInsertRowid);
}

function upsertAttachment(emailPk: number, part: ParsedAttachment, filename: string, status: string, extra: Record<string, string | number | null>) {
  const db = getDb();
  const now = nowIso();
  const existing = db
    .prepare(`SELECT id FROM attachments WHERE email_id = ? AND gmail_attachment_id = ?`)
    .get(emailPk, part.attachmentId) as { id: number } | undefined;
  if (!existing) {
    const result = db.prepare(
      `INSERT INTO attachments (
        email_id, original_filename, sanitized_filename, mime_type, file_size, gmail_attachment_id,
        upload_status, retryable, attempt_count, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)`,
    ).run(emailPk, part.filename, filename, part.mimeType, part.size, part.attachmentId, status, now, now);
    const id = Number(result.lastInsertRowid);
    applyAttachment(id, extra);
    return id;
  }
  applyAttachment(existing.id, { upload_status: status, sanitized_filename: filename, ...extra });
  return existing.id;
}

function applyAttachment(id: number, extra: Record<string, string | number | null>) {
  const assignments = Object.keys(extra).map((key) => `${key} = ?`);
  if (!assignments.length) return;
  getDb()
    .prepare(`UPDATE attachments SET ${assignments.join(", ")}, updated_at = ? WHERE id = ?`)
    .run(...Object.values(extra), nowIso(), id);
}

function storeRejection(emailPk: number, parsed: ParsedEmail, part: ParsedAttachment, reason: string) {
  const id = upsertAttachment(emailPk, part, part.filename, "skipped", { error_message: reason.slice(0, 500), retryable: 0 });
  addLog(getDb(), "attachment_skipped", "skipped", reason.slice(0, 500), emailPk, id);
  console.info(JSON.stringify({ event: "attachment_skipped", email_id: parsed.gmailMessageId, filename: part.filename }));
}

function storeFailure(
  emailPk: number,
  parsed: ParsedEmail,
  part: ParsedAttachment,
  filename: string,
  reason: string,
  retryable: boolean,
  digest?: string,
  size?: number,
) {
  const db = getDb();
  const row = db
    .prepare(`SELECT id, attempt_count, upload_status FROM attachments WHERE email_id = ? AND gmail_attachment_id = ?`)
    .get(emailPk, part.attachmentId) as { id: number; attempt_count: number; upload_status: string } | undefined;
  const id = row?.id ?? upsertAttachment(emailPk, part, filename, "failed", {});
  if (!row || row.upload_status !== "uploaded") {
    applyAttachment(id, {
      upload_status: "failed",
      error_message: reason.slice(0, 500),
      retryable: retryable ? 1 : 0,
      attempt_count: (row?.attempt_count || 0) + 1,
      sanitized_filename: filename,
      content_sha256: digest || null,
      file_size: size ?? part.size,
    });
  }
  addLog(db, "attachment_upload_failed", "failed", reason.slice(0, 500), emailPk, id);
  console.info(JSON.stringify({ event: "attachment_upload_failed", email_id: parsed.gmailMessageId, filename }));
}

function storeSuccess(
  emailPk: number,
  parsed: ParsedEmail,
  part: ParsedAttachment,
  filename: string,
  digest: string,
  size: number,
  uploaded: { fileId: string; duplicate: boolean; folderName: string },
  insight: AttachmentInsight | null,
) {
  const label = intentLabel(insight);
  const message = uploaded.duplicate
    ? "Attachment already existed in Drive"
    : label
      ? `Attachment uploaded to ${uploaded.folderName} (${label})`
      : `Attachment uploaded to ${uploaded.folderName}`;
  const id = upsertAttachment(emailPk, part, filename, "uploaded", {
    google_drive_file_id: uploaded.fileId,
    content_sha256: digest,
    error_message: null,
    retryable: 0,
    file_size: size,
    mime_type: part.mimeType,
    ai_description: insight?.description || null,
    ai_category: insight?.category || null,
    ai_attachment_type: insight?.attachmentType || null,
  });
  addLog(getDb(), uploaded.duplicate ? "attachment_duplicate" : "attachment_uploaded", "success", message, emailPk, id);
  console.info(JSON.stringify({ event: uploaded.duplicate ? "attachment_duplicate" : "attachment_uploaded", email_id: parsed.gmailMessageId, filename, message }));
}
