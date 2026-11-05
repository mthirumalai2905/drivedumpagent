import { getSettings } from "./config";
import { runCycle } from "./processor";

type PollerState = {
  running: boolean;
  lastPollAt: string | null;
  lastSuccessAt: string | null;
  lastError: string | null;
  started: boolean;
};

const state: PollerState = {
  running: false,
  lastPollAt: null,
  lastSuccessAt: null,
  lastError: null,
  started: false,
};

export function pollerState() {
  return state;
}

export async function runScheduledCycle(reprocessFailed = false) {
  if (state.running) {
    return { discovered: 0, matched: 0, uploaded: 0, failed: 0, skipped: 0, locked: true, detail: "already_running" };
  }
  state.running = true;
  state.lastPollAt = new Date().toISOString();
  try {
    const result = await runCycle(getSettings(), reprocessFailed);
    if (result.detail === "completed") {
      state.lastSuccessAt = new Date().toISOString();
      state.lastError = null;
    } else if (!["locked", "google_not_configured", "already_running", ""].includes(result.detail)) {
      state.lastError = result.detail;
    }
    return result;
  } catch (error) {
    state.lastError = "Processing cycle failed";
    console.info(JSON.stringify({ event: "poll_failed", message: error instanceof Error ? error.message : "failed" }));
    throw error;
  } finally {
    state.running = false;
  }
}

export function startScheduler() {
  if (process.env.VERCEL) return;
  if (state.started) return;
  let settings;
  try {
    settings = getSettings();
  } catch (error) {
    console.info(JSON.stringify({ event: "scheduler_disabled", message: error instanceof Error ? error.message : "config failed" }));
    return;
  }
  if (!settings.pollEnabled || settings.appEnv === "test") return;
  state.started = true;
  const tick = () => {
    runScheduledCycle().catch(() => {
      console.info(JSON.stringify({ event: "poll_failed", message: "Background poll failed and will retry on the next interval" }));
    });
  };
  setTimeout(tick, 3000);
  setInterval(tick, settings.pollIntervalSeconds * 1000);
  console.info(JSON.stringify({
    event: "scheduler_started",
    message: `Automatic Gmail polling every ${settings.pollIntervalSeconds} seconds`,
  }));
}
