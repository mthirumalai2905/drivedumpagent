import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { exchangeCode } from "@/lib/google";
import { requireUser } from "@/lib/http";
import { oauthStateValid } from "@/lib/session";

export const dynamic = "force-dynamic";

function page(title: string, body: string, status = 200) {
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>${title}</title></head><body style="font-family:Segoe UI,sans-serif;background:#101114;color:#eceae4;padding:40px"><main style="max-width:640px"><h1>${title}</h1>${body}<p><a href="/" style="color:#d6c7a1">Back to the dashboard</a></p></main></body></html>`;
  return new NextResponse(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

export async function GET(request: Request) {
  const denied = await requireUser();
  if (denied) return page("Sign in required", "<p>Sign in and start the Google connection again.</p>", 401);
  const url = new URL(request.url);
  const error = url.searchParams.get("error") || "";
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code") || "";
  const settings = getSettings();
  if (error) return page("Google authorization was not completed", "<p>No refresh token was created.</p>", 400);
  if (!oauthStateValid(state, settings.appSecretKey)) {
    return page("Authorization state was rejected", "<p>Start the connection again from the dashboard.</p>", 400);
  }
  if (!code) return page("Authorization code missing", "<p>Start the connection again.</p>", 400);
  try {
    const refresh = await exchangeCode(settings, code);
    return page(
      "Refresh token created",
      `<p>Copy this token into GOOGLE_REFRESH_TOKEN and restart. It is shown once and is not stored by the dashboard.</p><pre>${escapeHtml(refresh)}</pre>`,
    );
  } catch (caught) {
    return page("Google did not issue a refresh token", `<p>${escapeHtml(caught instanceof Error ? caught.message : "Authorization failed")}</p>`, 502);
  }
}
