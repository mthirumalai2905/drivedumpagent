import { createHash } from "crypto";

import type { Settings } from "./config";
import { contentTypeForUpload } from "./files";

const GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";
const DRIVE = "https://www.googleapis.com/drive/v3";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const FOLDER_MIME = "application/vnd.google-apps.folder";

export const GOOGLE_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/drive.file",
];

type TokenCache = { accessToken: string; expiresAt: number };
let tokenCache: TokenCache | null = null;

export class IntegrationError extends Error {
  retryable: boolean;
  statusCode: number;
  constructor(message: string, statusCode = 0, retryable = false) {
    super(message);
    this.statusCode = statusCode;
    this.retryable = retryable;
  }
}

function redact(value: string): string {
  return value
    .replace(/ya29\.[A-Za-z0-9_\-]+/g, "[redacted]")
    .replace(/1\/\/[A-Za-z0-9_\-]+/g, "[redacted]")
    .replace(/sk-[A-Za-z0-9]+/g, "[redacted]")
    .slice(0, 300);
}

async function googleError(response: Response): Promise<IntegrationError> {
  let code = "";
  let message = "";
  try {
    const payload = await response.json();
    const error = payload.error;
    if (error && typeof error === "object") {
      code = String(error.status || "");
      message = String(error.message || "").slice(0, 180);
    } else {
      code = String(error || "");
      message = String(payload.error_description || "").slice(0, 180);
    }
  } catch {
    code = "";
  }
  if (code === "unauthorized_client") {
    return new IntegrationError(
      "Google rejected this client id, client secret, and refresh token as a pair. Mint a new refresh token from Connect Google.",
      response.status,
      false,
    );
  }
  if (code === "invalid_grant") {
    return new IntegrationError(
      "Google refresh token was expired or revoked. Testing-mode OAuth clients expire refresh tokens after 7 days.",
      response.status,
      false,
    );
  }
  const retryable = response.status === 429 || response.status >= 500;
  const detail = redact(`Google API returned HTTP ${response.status} (${code} ${message})`.trim());
  return new IntegrationError(detail, response.status, retryable);
}

export async function getAccessToken(settings: Settings, force = false): Promise<string> {
  const now = Date.now();
  if (!force && tokenCache && tokenCache.expiresAt > now + 30_000) return tokenCache.accessToken;
  if (!settings.googleClientId || !settings.googleClientSecret || !settings.googleRefreshToken) {
    throw new IntegrationError("Google credentials are not set", 0, false);
  }
  const body = new URLSearchParams({
    client_id: settings.googleClientId,
    client_secret: settings.googleClientSecret,
    refresh_token: settings.googleRefreshToken,
    grant_type: "refresh_token",
  });
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) throw await googleError(response);
  const payload = await response.json();
  const accessToken = String(payload.access_token || "");
  if (!accessToken) throw new IntegrationError("Google did not return an access token", response.status, true);
  tokenCache = { accessToken, expiresAt: now + Number(payload.expires_in || 3600) * 1000 };
  return accessToken;
}

export function clearAccessToken() {
  tokenCache = null;
}

async function api(settings: Settings, url: string, init: RequestInit = {}, retryAuth = true): Promise<Response> {
  const token = await getAccessToken(settings);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch {
    throw new IntegrationError("Google API was unreachable", 0, true);
  }
  if (response.status === 401 && retryAuth) {
    clearAccessToken();
    return api(settings, url, init, false);
  }
  return response;
}

async function requestJson(settings: Settings, url: string, init?: RequestInit): Promise<Record<string, unknown>> {
  const response = await api(settings, url, init);
  if (!response.ok) throw await googleError(response);
  if (response.status === 204) return {};
  return response.json();
}

async function withRetry<T>(work: () => Promise<T>): Promise<T> {
  let last: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await work();
    } catch (error) {
      last = error;
      if (!(error instanceof IntegrationError) || !error.retryable || attempt === 2) break;
      await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
    }
  }
  throw last;
}

function shared(settings: Settings): string {
  if (!settings.googleDriveSupportsShared) return "";
  return "&supportsAllDrives=true&includeItemsFromAllDrives=true";
}

export async function gmailProfile(settings: Settings): Promise<string> {
  const payload = await withRetry(() => requestJson(settings, `${GMAIL}/profile`));
  const email = String(payload.emailAddress || "");
  if (!email) throw new IntegrationError("Gmail profile did not include an email address", 0, false);
  return email;
}

export async function listMessageIds(settings: Settings): Promise<string[]> {
  const found: string[] = [];
  let pageToken = "";
  while (found.length < settings.maxMessagesPerCycle) {
    const params = new URLSearchParams({
      q: `newer_than:${settings.emailLookbackMinutes}m -in:chats`,
      maxResults: String(Math.min(50, settings.maxMessagesPerCycle - found.length)),
    });
    if (pageToken) params.set("pageToken", pageToken);
    const payload = await withRetry(() => requestJson(settings, `${GMAIL}/messages?${params}`));
    for (const item of (payload.messages as Array<{ id?: string }> | undefined) || []) {
      if (item.id) found.push(item.id);
    }
    pageToken = String(payload.nextPageToken || "");
    if (!pageToken) break;
  }
  return found.slice(0, settings.maxMessagesPerCycle);
}

export async function getMessage(settings: Settings, messageId: string): Promise<Record<string, unknown>> {
  return withRetry(() => requestJson(settings, `${GMAIL}/messages/${encodeURIComponent(messageId)}?format=full`));
}

export async function getAttachment(settings: Settings, messageId: string, attachmentId: string): Promise<Buffer> {
  const payload = await withRetry(() =>
    requestJson(
      settings,
      `${GMAIL}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`,
    ),
  );
  const data = String(payload.data || "");
  if (!data) throw new IntegrationError("Gmail attachment response did not include data", 0, true);
  return Buffer.from(data, "base64url");
}

export async function getFolder(settings: Settings, folderId: string): Promise<Record<string, unknown>> {
  const payload = await withRetry(() =>
    requestJson(settings, `${DRIVE}/files/${encodeURIComponent(folderId)}?fields=id,name,mimeType,trashed${shared(settings)}`),
  );
  if (payload.mimeType !== FOLDER_MIME || payload.trashed) {
    throw new IntegrationError("GOOGLE_DRIVE_FOLDER_ID does not point at an active folder", 0, false);
  }
  return payload;
}

export async function ensureChildFolder(settings: Settings, parentId: string, name: string): Promise<string> {
  if (!/^[A-Za-z0-9_-]+$/.test(parentId) || !/^[A-Za-z0-9][A-Za-z0-9 ]{0,40}$/.test(name)) {
    throw new IntegrationError("Drive folder name is invalid", 0, false);
  }
  const q = `mimeType = '${FOLDER_MIME}' and name = '${name}' and '${parentId}' in parents and trashed = false`;
  const params = new URLSearchParams({
    q,
    spaces: "drive",
    pageSize: "1",
    fields: "files(id,name)",
  });
  const payload = await withRetry(() => requestJson(settings, `${DRIVE}/files?${params}${shared(settings)}`));
  const files = (payload.files as Array<{ id?: string }> | undefined) || [];
  if (files[0]?.id) return String(files[0].id);
  const created = await withRetry(() =>
    requestJson(settings, `${DRIVE}/files?fields=id${shared(settings)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, mimeType: FOLDER_MIME, parents: [parentId] }),
    }),
  );
  if (!created.id) throw new IntegrationError("Google Drive did not create the folder", 0, true);
  return String(created.id);
}

export async function createRootFolder(settings: Settings, name: string): Promise<string> {
  const safe = name.replace(/[^\w .()-]/g, "").trim().slice(0, 80) || "Back Office";
  const created = await withRetry(() =>
    requestJson(settings, `${DRIVE}/files?fields=id,name${shared(settings)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: safe, mimeType: FOLDER_MIME }),
    }),
  );
  if (!created.id) throw new IntegrationError("Google Drive did not create the folder", 0, true);
  return String(created.id);
}

export function dedupeKey(messageId: string, attachmentId: string): string {
  return createHash("sha256").update(`${messageId}:${attachmentId}`).digest("hex");
}

export function contentDigest(data: Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

export function escapeDriveLiteral(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

export function nameInFolderQuery(parentId: string, filename: string): string {
  return `name = '${escapeDriveLiteral(filename)}' and '${parentId}' in parents and trashed = false and mimeType != '${FOLDER_MIME}'`;
}

export function contentHashQuery(digest: string): string {
  return `appProperties has { key = 'bo_sha256' and value = '${digest}' } and trashed = false`;
}

async function firstFileId(settings: Settings, q: string): Promise<string | null> {
  const params = new URLSearchParams({ q, spaces: "drive", pageSize: "1", fields: "files(id)" });
  const payload = await withRetry(() => requestJson(settings, `${DRIVE}/files?${params}${shared(settings)}`));
  const files = (payload.files as Array<{ id?: string }> | undefined) || [];
  return files[0]?.id ? String(files[0].id) : null;
}

export async function findByDedupeKey(settings: Settings, key: string): Promise<string | null> {
  if (!/^[0-9a-f]+$/.test(key)) return null;
  const q = `appProperties has { key = 'bo_dedupe' and value = '${key}' } and trashed = false`;
  return firstFileId(settings, q);
}

export async function findByContentHash(settings: Settings, digest: string): Promise<string | null> {
  if (!/^[0-9a-f]{64}$/.test(digest)) return null;
  return firstFileId(settings, contentHashQuery(digest));
}

export async function findByNameInFolder(settings: Settings, parentId: string, filename: string): Promise<string | null> {
  if (!/^[A-Za-z0-9_-]+$/.test(parentId) || !filename) return null;
  return firstFileId(settings, nameInFolderQuery(parentId, filename));
}

const childFolders = new Map<string, string>();
const filedByKey = new Map<string, string>();
const filedByHash = new Map<string, string>();
const filedByName = new Map<string, string>();
const inflight = new Map<string, Promise<string>>();

function recall(parentId: string, filename: string, digest: string, key: string): string | null {
  return filedByKey.get(key) || filedByHash.get(digest) || filedByName.get(`${parentId}/${filename}`) || null;
}

function remember(parentId: string, filename: string, digest: string, key: string, fileId: string) {
  filedByKey.set(key, fileId);
  filedByHash.set(digest, fileId);
  filedByName.set(`${parentId}/${filename}`, fileId);
}

async function locateCopy(
  settings: Settings,
  parentId: string,
  filename: string,
  digest: string,
  key: string,
): Promise<string | null> {
  const cached = recall(parentId, filename, digest, key);
  if (cached) return cached;
  const byKey = await findByDedupeKey(settings, key);
  if (byKey) return byKey;
  const byHash = await findByContentHash(settings, digest);
  if (byHash) return byHash;
  return findByNameInFolder(settings, parentId, filename);
}

export async function uploadBytes(input: {
  settings: Settings;
  messageId: string;
  attachmentId: string;
  filename: string;
  mimeType: string;
  data: Buffer;
  folderName: string;
}): Promise<{ fileId: string; duplicate: boolean; folderName: string }> {
  const destination = [
    "PDFs",
    "Presentations",
    "Images",
    "Sheets",
    "Documents",
    "Videos",
    "Other",
  ].includes(input.folderName)
    ? input.folderName
    : "Other";
  if (!input.settings.googleDriveFolderId) {
    throw new IntegrationError("GOOGLE_DRIVE_FOLDER_ID is not configured", 0, false);
  }
  const digest = contentDigest(input.data);
  const key = dedupeKey(input.messageId, input.attachmentId);
  const claim = `${destination}/${input.filename}`;
  const pending = inflight.get(digest) || inflight.get(`name:${claim}`);
  if (pending) {
    const fileId = await pending;
    return { fileId, duplicate: true, folderName: destination };
  }
  let resolveFile: (fileId: string) => void = () => {};
  let rejectFile: (error: unknown) => void = () => {};
  const gate = new Promise<string>((resolve, reject) => {
    resolveFile = resolve;
    rejectFile = reject;
  });
  gate.catch(() => {});
  inflight.set(digest, gate);
  inflight.set(`name:${claim}`, gate);
  try {
    const result = await storeOnce(input, destination, digest, key);
    resolveFile(result.fileId);
    return result;
  } catch (error) {
    inflight.delete(digest);
    inflight.delete(`name:${claim}`);
    rejectFile(error);
    throw error;
  }
}

async function storeOnce(
  input: {
    settings: Settings;
    messageId: string;
    attachmentId: string;
    filename: string;
    mimeType: string;
    data: Buffer;
  },
  destination: string,
  digest: string,
  key: string,
): Promise<{ fileId: string; duplicate: boolean; folderName: string }> {
  const early = filedByKey.get(key) || filedByHash.get(digest);
  if (early) return { fileId: early, duplicate: true, folderName: destination };
  const byKey = await findByDedupeKey(input.settings, key);
  if (byKey) {
    filedByKey.set(key, byKey);
    filedByHash.set(digest, byKey);
    return { fileId: byKey, duplicate: true, folderName: destination };
  }
  const byHash = await findByContentHash(input.settings, digest);
  if (byHash) {
    filedByKey.set(key, byHash);
    filedByHash.set(digest, byHash);
    return { fileId: byHash, duplicate: true, folderName: destination };
  }
  let parentId = childFolders.get(destination);
  if (!parentId) {
    parentId = await ensureChildFolder(input.settings, input.settings.googleDriveFolderId, destination);
    childFolders.set(destination, parentId);
  }
  const named = filedByName.get(`${parentId}/${input.filename}`) || (await findByNameInFolder(input.settings, parentId, input.filename));
  if (named) {
    remember(parentId, input.filename, digest, key, named);
    return { fileId: named, duplicate: true, folderName: destination };
  }
  const fileId = await postFile(input, parentId, digest, key);
  remember(parentId, input.filename, digest, key, fileId);
  return { fileId, duplicate: false, folderName: destination };
}

const RESUMABLE_AT = 4 * 1024 * 1024;

function driveUploadLocation(value: string | null): string {
  let url: URL;
  try {
    url = new URL(value || "");
  } catch {
    throw new IntegrationError("Google Drive did not start the upload", 0, true);
  }
  if (url.protocol !== "https:" || !url.hostname.endsWith("googleapis.com")) {
    throw new IntegrationError("Google Drive did not start the upload", 0, false);
  }
  return url.toString();
}

async function postFile(
  input: {
    settings: Settings;
    filename: string;
    mimeType: string;
    data: Buffer;
  },
  parentId: string,
  digest: string,
  key: string,
): Promise<string> {
  const mime = contentTypeForUpload(input.filename, input.mimeType);
  const metadata = JSON.stringify({
    name: input.filename,
    parents: [parentId],
    appProperties: { bo_dedupe: key, bo_sha256: digest },
  });
  let last: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (attempt) {
      const found = await locateCopy(input.settings, parentId, input.filename, digest, key);
      if (found) return found;
      await new Promise((resolve) => setTimeout(resolve, 400 * attempt));
    }
    try {
      const fileId = input.data.length >= RESUMABLE_AT
        ? await postResumable(input.settings, metadata, mime, input.data)
        : await postMultipart(input.settings, metadata, mime, input.data);
      return fileId;
    } catch (error) {
      last = error;
      if (!(error instanceof IntegrationError) || !error.retryable || attempt === 2) break;
    }
  }
  throw last;
}

async function postMultipart(settings: Settings, metadata: string, mime: string, data: Buffer): Promise<string> {
  const boundary = `bo${createHash("sha256").update(String(Math.random())).digest("hex").slice(0, 24)}`;
  const preamble = Buffer.from(
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${metadata}\r\n--${boundary}\r\nContent-Type: ${mime}\r\n\r\n`,
    "utf8",
  );
  const closing = Buffer.from(`\r\n--${boundary}--\r\n`, "utf8");
  const payload = await requestJson(settings, `${UPLOAD}?uploadType=multipart&fields=id${shared(settings)}`, {
    method: "POST",
    headers: { "Content-Type": `multipart/related; boundary=${boundary}` },
    body: Buffer.concat([preamble, data, closing]),
  });
  if (!payload.id) throw new IntegrationError("Google Drive upload did not return a file id", 0, true);
  return String(payload.id);
}

async function postResumable(settings: Settings, metadata: string, mime: string, data: Buffer): Promise<string> {
  const start = await api(settings, `${UPLOAD}?uploadType=resumable&fields=id${shared(settings)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=UTF-8",
      "X-Upload-Content-Type": mime,
      "X-Upload-Content-Length": String(data.length),
    },
    body: metadata,
  });
  if (!start.ok) throw await googleError(start);
  const location = driveUploadLocation(start.headers.get("location"));
  const put = await api(settings, location, {
    method: "PUT",
    headers: {
      "Content-Type": mime,
      "Content-Length": String(data.length),
      "Content-Range": `bytes 0-${data.length - 1}/${data.length}`,
    },
    body: data as unknown as NonNullable<RequestInit["body"]>,
  });
  if (!put.ok) throw await googleError(put);
  const payload = (await put.json()) as { id?: string };
  if (!payload.id) throw new IntegrationError("Google Drive upload did not return a file id", 0, true);
  return String(payload.id);
}

export async function exchangeCode(settings: Settings, code: string): Promise<string> {
  const body = new URLSearchParams({
    code,
    client_id: settings.googleClientId,
    client_secret: settings.googleClientSecret,
    redirect_uri: settings.googleOauthRedirectUri,
    grant_type: "authorization_code",
  });
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) throw await googleError(response);
  const payload = await response.json();
  const refresh = String(payload.refresh_token || "");
  if (!refresh) {
    throw new IntegrationError("Google did not return a refresh token. Start Connect Google again.", response.status, false);
  }
  return refresh;
}
