import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { SESSION_COOKIE, SESSION_MAX_AGE, secretsEqual, signSession } from "@/lib/session";

export async function POST(request: Request) {
  const form = await request.formData();
  const username = String(form.get("username") || "");
  const password = String(form.get("password") || "");
  const settings = getSettings();
  const ok = secretsEqual(username, settings.dashboardUsername) && secretsEqual(password, settings.dashboardPassword);
  const origin = new URL(request.url).origin;
  if (!ok) return NextResponse.redirect(`${origin}/login?error=1`, 303);
  const response = NextResponse.redirect(`${origin}/`, 303);
  response.cookies.set(SESSION_COOKIE, signSession(settings.dashboardUsername, settings.appSecretKey), {
    httpOnly: true,
    sameSite: "lax",
    secure: settings.secureCookies,
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return response;
}
