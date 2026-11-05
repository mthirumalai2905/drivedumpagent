import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { requireUser } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function GET() {
  const denied = await requireUser();
  if (denied) return denied;
  const settings = getSettings();
  const flags = [
    ["APP_SECRET_KEY", settings.appSecretKey],
    ["DASHBOARD_PASSWORD", settings.dashboardPassword],
    ["GOOGLE_CLIENT_ID", settings.googleClientId],
    ["GOOGLE_CLIENT_SECRET", settings.googleClientSecret],
    ["GOOGLE_REFRESH_TOKEN", settings.googleRefreshToken],
    ["GOOGLE_OAUTH_REDIRECT_URI", settings.googleOauthRedirectUri],
    ["GOOGLE_DRIVE_FOLDER_ID", settings.googleDriveFolderId],
    ["GOOGLE_GMAIL_USER", settings.googleGmailUser],
    ["DEEPSEEK_API_KEY", settings.deepseekApiKey],
    ["DEEPSEEK_MODEL", settings.deepseekModel],
    ["DATABASE_URL", settings.databasePath],
    ["TRIGGER_KEYWORD", settings.keywords.join(",")],
  ].map(([name, value]) => ({ name, configured: Boolean(value) }));
  return NextResponse.json({
    app_env: settings.appEnv,
    app_name: settings.appName,
    gmail_user: settings.googleGmailUser,
    trigger_keywords: settings.keywords,
    poll_interval_seconds: settings.pollIntervalSeconds,
    poll_enabled: settings.pollEnabled,
    email_lookback_minutes: settings.emailLookbackMinutes,
    max_attachment_bytes: settings.maxAttachmentBytes,
    database_backend: "sqlite",
    deepseek_model: settings.deepseekModel,
    flags,
  });
}
