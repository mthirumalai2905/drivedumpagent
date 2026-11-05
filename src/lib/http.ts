import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { readSession, SESSION_COOKIE } from "@/lib/session";

export async function requireUser(): Promise<NextResponse | null> {
  const settings = getSettings();
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!readSession(token, settings.appSecretKey)) {
    return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  }
  return null;
}
