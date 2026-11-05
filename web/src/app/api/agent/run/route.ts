import { NextResponse } from "next/server";

import { requireUser } from "@/lib/http";
import { runScheduledCycle } from "@/lib/poller";

export const dynamic = "force-dynamic";

const hits: number[] = [];

export async function POST(request: Request) {
  const denied = await requireUser();
  if (denied) return denied;
  const now = Date.now();
  while (hits.length && hits[0] < now - 60_000) hits.shift();
  if (hits.length >= 6) return NextResponse.json({ detail: "Too many requests" }, { status: 429 });
  hits.push(now);
  const body = await request.json().catch(() => ({}));
  const result = await runScheduledCycle(Boolean(body.reprocess_failed));
  if (result.detail === "already_running") {
    return NextResponse.json({ detail: "A processing cycle is already running" }, { status: 409 });
  }
  return NextResponse.json(result);
}
