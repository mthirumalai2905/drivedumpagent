"use client";

import { useEffect, useState } from "react";

type Service = { state: string; detail: string };

type Health = {
  poll_running: boolean;
  poll_interval_seconds: number;
  last_success_at: string | null;
  last_error: string | null;
  gmail: Service;
  google_drive: Service;
  deepseek: Service;
  database: Service;
};

type Stats = {
  emails_scanned: number;
  trigger_matches: number;
  uploads_succeeded: number;
  uploads_failed: number;
  pending: number;
};

type LogItem = {
  id: number;
  created_at: string;
  subject: string | null;
  sender: string | null;
  filename: string | null;
  event_type: string;
  status: string;
  message: string;
  error_message: string | null;
};

type ConfigStatus = {
  app_env: string;
  gmail_user: string;
  trigger_keywords: string[];
  deepseek_model: string;
  flags: Array<{ name: string; configured: boolean }>;
};

const LABELS: Record<string, string> = {
  attachment_uploaded: "Filed",
  attachment_duplicate: "Already in Drive",
  attachment_upload_failed: "Upload failed",
  attachment_skipped: "Skipped",
  trigger_matched: "Keyword matched",
  trigger_missed: "No keyword",
  poll_failed: "Mailbox check failed",
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Authentication required");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload as T;
}

function clock(value: string | null) {
  if (!value) return "not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "not yet";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function tone(state: string) {
  if (state === "operational") return "ok";
  if (state === "error") return "bad";
  return "wait";
}

export function Dashboard({ appName }: { appName: string }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [note, setNote] = useState("");
  const [folderNote, setFolderNote] = useState("");
  const [folderName, setFolderName] = useState("Back Office");

  async function refresh() {
    const [healthData, statsData, logData, configData] = await Promise.all([
      api<Health>("/health/integrations"),
      api<Stats>("/api/stats"),
      api<{ items: LogItem[] }>("/api/logs?limit=10"),
      api<ConfigStatus>("/api/config/status"),
    ]);
    setHealth(healthData);
    setStats(statsData);
    setLogs(logData.items);
    setConfig(configData);
  }

  useEffect(() => {
    refresh().catch((error: Error) => setNote(error.message));
    const timer = setInterval(() => {
      refresh().catch(() => {});
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  async function run(reprocess: boolean) {
    setNote(reprocess ? "Retrying failed files…" : "Checking the mailbox now…");
    try {
      const result = await api<{ uploaded: number; failed: number }>("/api/agent/run", {
        method: "POST",
        body: JSON.stringify({ reprocess_failed: reprocess }),
      });
      setNote(`${result.uploaded} filed, ${result.failed} failed.`);
      await refresh();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "The check failed");
    }
  }

  const services: Array<[string, Service]> = health
    ? [
        ["Gmail", health.gmail],
        ["Drive", health.google_drive],
        ["DeepSeek", health.deepseek],
        ["Database", health.database],
      ]
    : [];
  const missing = config?.flags.filter((flag) => !flag.configured) ?? [];

  return (
    <>
      <header className="mast">
        <div>
          <p className="brand">Synx</p>
          <h1>{appName}</h1>
        </div>
        <form action="/logout" method="post">
          <button type="submit">Sign out</button>
        </form>
      </header>

      <main className="sheet">
        <p className="live">
          {health?.poll_running ? "Checking mail now" : `Checked ${clock(health?.last_success_at ?? null)}`}
          {health ? ` · every ${health.poll_interval_seconds}s` : ""}
          {health?.last_error ? ` · ${health.last_error}` : ""}
        </p>

        <ul className="services">
          {services.map(([name, service]) => (
            <li key={name} className={tone(service.state)} title={service.detail}>
              <span>{name}</span>
              <strong>{service.state === "operational" ? "Ready" : service.state.replaceAll("_", " ")}</strong>
            </li>
          ))}
        </ul>

        <dl className="counts">
          <div><dt>Scanned</dt><dd>{stats?.emails_scanned ?? "–"}</dd></div>
          <div><dt>Matched</dt><dd>{stats?.trigger_matches ?? "–"}</dd></div>
          <div><dt>Filed</dt><dd>{stats?.uploads_succeeded ?? "–"}</dd></div>
          <div><dt>Failed</dt><dd>{stats?.uploads_failed ?? "–"}</dd></div>
          <div><dt>Waiting</dt><dd>{stats?.pending ?? "–"}</dd></div>
        </dl>

        <section className="feed-block">
          <div className="row">
            <h2>Latest filings</h2>
            <div className="row-actions">
              <button type="button" onClick={() => run(false)}>Check now</button>
              <button type="button" onClick={() => run(true)}>Retry failed</button>
            </div>
          </div>
          {note ? <p className="note">{note}</p> : null}
          {logs.length === 0 ? (
            <p className="empty">Nothing filed yet. Matching mail shows up here.</p>
          ) : (
            <ol className="feed">
              {logs.map((item) => (
                <li key={item.id} className={item.status}>
                  <time>{clock(item.created_at)}</time>
                  <div>
                    <strong>{LABELS[item.event_type] || item.event_type}</strong>
                    <span>{item.filename || item.subject || "—"}</span>
                    <p>{[item.sender, item.error_message || item.message].filter(Boolean).join(" · ")}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="setup">
          <div className="row">
            <h2>Setup</h2>
            <a href="/oauth/google/start">Connect Google</a>
          </div>
          <p className="note">
            {config?.gmail_user || "Mailbox not set"}
            {" · "}
            {(config?.trigger_keywords || []).join(", ") || "no keyword"}
            {" · "}
            {config?.deepseek_model || "no model"}
            {" · "}
            {config?.app_env}
          </p>
          {missing.length > 0 ? (
            <p className="missing">Still needed: {missing.map((flag) => flag.name).join(", ")}</p>
          ) : null}
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              setFolderNote("Creating the folder…");
              try {
                const created = await api<{ detail: string; id: string }>("/api/drive/folder", {
                  method: "POST",
                  body: JSON.stringify({ name: folderName }),
                });
                setFolderNote(`${created.detail} ${created.id}`);
              } catch (error) {
                setFolderNote(error instanceof Error ? error.message : "The folder was not created");
              }
            }}
          >
            <label htmlFor="folder-name">New Drive folder</label>
            <div className="row-actions">
              <input id="folder-name" value={folderName} maxLength={120} onChange={(event) => setFolderName(event.target.value)} required />
              <button type="submit">Create</button>
            </div>
            {folderNote ? <p className="note">{folderNote}</p> : null}
          </form>
        </section>
      </main>
    </>
  );
}
