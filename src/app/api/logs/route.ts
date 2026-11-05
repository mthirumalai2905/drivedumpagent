import { NextResponse } from "next/server";

import { getDb } from "@/lib/db";
import { requireUser } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireUser();
  if (denied) return denied;
  const url = new URL(request.url);
  const status = url.searchParams.get("status") || "all";
  const limit = Math.min(10, Math.max(1, Number(url.searchParams.get("limit") || 10)));
  const offset = 0;
  const selected = ["success", "failed", "pending"].includes(status) ? status : "";
  const where = [
    "logs.event_type NOT IN ('emails_discovered', 'poll_completed')",
    selected ? "logs.status = ?" : "",
  ].filter(Boolean).join(" AND ");
  const params = selected ? [selected] : [];
  const db = getDb();
  const total = Number(
    (db.prepare(`SELECT COUNT(*) AS n FROM processing_logs logs WHERE ${where}`).get(...params) as { n: number }).n,
  );
  const items = db
    .prepare(
      `SELECT logs.id, logs.created_at, logs.event_type, logs.status, logs.message,
              emails.subject, emails.sender, attachments.sanitized_filename AS filename,
              attachments.upload_status, attachments.error_message
       FROM processing_logs logs
       LEFT JOIN emails ON emails.id = logs.email_id
       LEFT JOIN attachments ON attachments.id = logs.attachment_id
       WHERE ${where}
       ORDER BY logs.created_at DESC, logs.id DESC
       LIMIT ? OFFSET ?`,
    )
    .all(...params, limit, offset);
  return NextResponse.json({ items, total, limit, offset });
}
