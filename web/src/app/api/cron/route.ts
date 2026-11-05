import { timingSafeEqual } from "crypto";
import { NextResponse } from "next/server";

import { runScheduledCycle } from "@/lib/poller";

export const dynamic = "force-dynamic";

function authorized(request: Request): boolean {
  const secret = process.env.CRON_SECRET || "";
  if (!secret) return false;
  const header = request.headers.get("authorization") || "";
  const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
  const left = Buffer.from(provided);
  const right = Buffer.from(secret);
  return left.length === right.length && timingSafeEqual(left, right);
}

async function run(request: Request) {
  const fromVercel = request.headers.get("x-vercel-cron") === "1" && Boolean(process.env.VERCEL);
  if (!fromVercel && !process.env.CRON_SECRET) {
    return NextResponse.json(
      { detail: "The in-process scheduler is already running. Set CRON_SECRET only for an external cron." },
      { status: 404 },
    );
  }
  if (!fromVercel && !authorized(request)) {
    return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  }
  const result = await runScheduledCycle(false);
  return NextResponse.json(result);
}

export function GET(request: Request) {
  return run(request);
}

export function POST(request: Request) {
  return run(request);
}
