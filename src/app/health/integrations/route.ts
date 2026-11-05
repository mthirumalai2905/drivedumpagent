import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { listModels } from "@/lib/deepseek";
import { getDb } from "@/lib/db";
import { getFolder, gmailProfile, IntegrationError } from "@/lib/google";
import { requireUser } from "@/lib/http";
import { pollerState } from "@/lib/poller";

export const dynamic = "force-dynamic";

let cache: { at: number; body: unknown } | null = null;

export async function GET() {
  const denied = await requireUser();
  if (denied) return denied;
  if (cache && Date.now() - cache.at < 20_000) return NextResponse.json(cache.body);
  const settings = getSettings();
  const poller = pollerState();
  let database = { state: "operational", detail: "Database accepted a query" };
  try {
    getDb().prepare("SELECT 1").get();
  } catch {
    database = { state: "error", detail: "Database query failed" };
  }
  const body = {
    application: database.state === "operational" ? "ok" : "degraded",
    database,
    gmail: await gmailReport(settings),
    google_drive: await driveReport(settings),
    deepseek: await deepseekReport(settings),
    last_poll_at: poller.lastPollAt,
    last_success_at: poller.lastSuccessAt,
    last_error: poller.lastError,
    poll_running: poller.running,
    poll_interval_seconds: settings.pollIntervalSeconds,
    poll_enabled: settings.pollEnabled,
  };
  cache = { at: Date.now(), body };
  return NextResponse.json(body);
}

async function gmailReport(settings: ReturnType<typeof getSettings>) {
  if (!settings.googleRefreshToken) return { state: "not_configured", detail: "Gmail credentials are not set" };
  try {
    const email = await gmailProfile(settings);
    if (settings.googleGmailUser && email.toLowerCase() !== settings.googleGmailUser.toLowerCase()) {
      return { state: "connected", detail: "Authenticated, but the account does not match GOOGLE_GMAIL_USER" };
    }
    return { state: "operational", detail: "Gmail mailbox is reachable" };
  } catch (error) {
    return { state: "error", detail: error instanceof Error ? error.message.slice(0, 300) : "Gmail check failed" };
  }
}

async function driveReport(settings: ReturnType<typeof getSettings>) {
  if (!settings.googleRefreshToken) return { state: "not_configured", detail: "Google Drive credentials are not set" };
  if (!settings.googleDriveFolderId) {
    return { state: "configured", detail: "Create a destination folder in the dashboard and set GOOGLE_DRIVE_FOLDER_ID" };
  }
  try {
    const folder = await getFolder(settings, settings.googleDriveFolderId);
    return { state: "operational", detail: `Destination folder is reachable (${String(folder.name || "folder")})` };
  } catch (error) {
    const message = error instanceof Error ? error.message.slice(0, 300) : "Drive check failed";
    if (error instanceof IntegrationError && [400, 401].includes(error.statusCode)) {
      return { state: "error", detail: message };
    }
    return { state: "connected", detail: message };
  }
}

async function deepseekReport(settings: ReturnType<typeof getSettings>) {
  if (!settings.deepseekApiKey && !settings.deepseekModel) {
    return { state: "not_configured", detail: "DeepSeek is optional and not configured" };
  }
  if (!settings.deepseekApiKey || !settings.deepseekModel) {
    return { state: "configured", detail: "Set both DEEPSEEK_API_KEY and DEEPSEEK_MODEL to enable DeepSeek" };
  }
  try {
    const models = await listModels(settings);
    if (!models.includes(settings.deepseekModel)) {
      return { state: "connected", detail: "DeepSeek responded, but DEEPSEEK_MODEL is not in the model list" };
    }
    return { state: "operational", detail: "Configured DeepSeek model is available" };
  } catch (error) {
    return { state: "error", detail: error instanceof Error ? error.message.slice(0, 300) : "DeepSeek check failed" };
  }
}
