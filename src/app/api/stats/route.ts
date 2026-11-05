import { NextResponse } from "next/server";

import { getDb } from "@/lib/db";
import { requireUser } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function GET() {
  const denied = await requireUser();
  if (denied) return denied;
  const db = getDb();
  const count = (sql: string) => Number((db.prepare(sql).get() as { n: number }).n);
  return NextResponse.json({
    emails_scanned: count("SELECT COUNT(*) AS n FROM emails"),
    trigger_matches: count("SELECT COUNT(*) AS n FROM emails WHERE trigger_matched = 1"),
    attachments_detected: count("SELECT COUNT(*) AS n FROM attachments"),
    uploads_succeeded: count("SELECT COUNT(*) AS n FROM attachments WHERE upload_status = 'uploaded'"),
    uploads_failed: count("SELECT COUNT(*) AS n FROM attachments WHERE upload_status = 'failed'"),
    pending: count("SELECT COUNT(*) AS n FROM emails WHERE processing_status IN ('pending', 'processing')"),
  });
}
