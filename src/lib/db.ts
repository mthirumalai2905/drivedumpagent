import { createRequire } from "module";
import type { DatabaseSync } from "node:sqlite";

import { getSettings } from "./config";

const require = createRequire(import.meta.url);

let database: DatabaseSync | null = null;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gmail_message_id TEXT NOT NULL UNIQUE,
  sender TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  trigger_matched INTEGER NOT NULL DEFAULT 0,
  processing_status TEXT NOT NULL,
  ai_summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  original_filename TEXT NOT NULL,
  sanitized_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL DEFAULT 0,
  content_sha256 TEXT,
  gmail_attachment_id TEXT NOT NULL,
  google_drive_file_id TEXT,
  upload_status TEXT NOT NULL,
  error_message TEXT,
  retryable INTEGER NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  ai_description TEXT,
  ai_category TEXT,
  ai_attachment_type TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (email_id, gmail_attachment_id)
);
CREATE TABLE IF NOT EXISTS processing_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER REFERENCES emails(id) ON DELETE CASCADE,
  attachment_id INTEGER REFERENCES attachments(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_locks (
  name TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  acquired_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
`;

export function getDb(): DatabaseSync {
  if (database) return database;
  const { DatabaseSync } = require("node:sqlite") as typeof import("node:sqlite");
  const settings = getSettings();
  database = new DatabaseSync(settings.databasePath);
  const journal = process.env.VERCEL ? "DELETE" : "WAL";
  database.exec(`PRAGMA journal_mode = ${journal}; PRAGMA foreign_keys = ON;`);
  database.exec(SCHEMA);
  database
    .prepare(`DELETE FROM processing_logs WHERE event_type IN ('emails_discovered', 'poll_completed')`)
    .run();
  return database;
}

export function closeDbForTests() {
  database?.close();
  database = null;
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function addLog(
  db: DatabaseSync,
  eventType: string,
  status: string,
  message: string,
  emailId: number | null = null,
  attachmentId: number | null = null,
) {
  db.prepare(
    `INSERT INTO processing_logs (email_id, attachment_id, event_type, status, message, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(emailId, attachmentId, eventType, status, message.slice(0, 500), nowIso());
}

export function acquireLock(db: DatabaseSync, owner: string, ttlSeconds: number): boolean {
  const now = Math.floor(Date.now() / 1000);
  const expires = now + ttlSeconds;
  const updated = db
    .prepare(
      `UPDATE worker_locks SET owner = ?, acquired_at = ?, expires_at = ?
       WHERE name = 'gmail_poller' AND (expires_at <= ? OR owner = ?)`,
    )
    .run(owner, now, expires, now, owner);
  if (updated.changes === 1) return true;
  try {
    db.prepare(
      `INSERT INTO worker_locks (name, owner, acquired_at, expires_at) VALUES ('gmail_poller', ?, ?, ?)`,
    ).run(owner, now, expires);
    return true;
  } catch {
    return false;
  }
}

export function releaseLock(db: DatabaseSync, owner: string) {
  const now = Math.floor(Date.now() / 1000);
  db.prepare(
    `UPDATE worker_locks SET expires_at = ? WHERE name = 'gmail_poller' AND owner = ?`,
  ).run(now, owner);
}
