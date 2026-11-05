import { createHash } from "crypto";

export type ParsedAttachment = {
  filename: string;
  mimeType: string;
  size: number;
  attachmentId: string;
  data: Buffer | null;
};

export type ParsedEmail = {
  gmailMessageId: string;
  sender: string;
  subject: string;
  body: string;
  receivedAt: string;
  attachments: ParsedAttachment[];
};

function decodeB64(data: string): Buffer {
  if (!data) return Buffer.alloc(0);
  return Buffer.from(data, "base64url");
}

function headersOf(part: Record<string, unknown>): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const item of (part.headers as Array<{ name?: string; value?: string }> | undefined) || []) {
    const name = String(item.name || "").toLowerCase();
    if (name) headers[name] = String(item.value || "");
  }
  return headers;
}

function stripHtml(value: string): string {
  return value
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function walk(part: Record<string, unknown>, plain: string[], rich: string[], attachments: ParsedAttachment[], index: number[]) {
  const mime = String(part.mimeType || "application/octet-stream");
  const filename = String(part.filename || "");
  const body = (part.body as { attachmentId?: string; data?: string; size?: number } | undefined) || {};
  const disposition = headersOf(part)["content-disposition"] || "";
  const isAttachment = Boolean(filename) || disposition.toLowerCase().includes("attachment");
  if (isAttachment && !mime.startsWith("multipart/")) {
    const rawId = String(body.attachmentId || "");
    const data = body.data && !rawId ? decodeB64(body.data) : null;
    const size = Number(body.size || (data ? data.length : 0));
    index[0] += 1;
    let attachmentId = rawId;
    if (!attachmentId && data) attachmentId = `inline-${createHash("sha256").update(data).digest("hex").slice(0, 32)}`;
    if (!attachmentId) {
      const nameHash = createHash("sha256").update(filename).digest("hex").slice(0, 16);
      attachmentId = `part-${index[0]}-${size}-${nameHash}`;
    }
    attachments.push({
      filename: filename || "attachment",
      mimeType: mime,
      size,
      attachmentId,
      data,
    });
  } else if (mime === "text/plain" && body.data) {
    plain.push(decodeB64(body.data).toString("utf8"));
  } else if (mime === "text/html" && body.data) {
    rich.push(decodeB64(body.data).toString("utf8"));
  }
  for (const child of (part.parts as Record<string, unknown>[] | undefined) || []) walk(child, plain, rich, attachments, index);
}

export function parseGmailMessage(message: Record<string, unknown>): ParsedEmail {
  const payload = (message.payload as Record<string, unknown> | undefined) || {};
  const headers = headersOf(payload);
  const plain: string[] = [];
  const rich: string[] = [];
  const attachments: ParsedAttachment[] = [];
  walk(payload, plain, rich, attachments, [0]);
  let body = plain.length ? plain.join("\n") : rich.map(stripHtml).join("\n");
  if (body.length > 512_000) body = body.slice(0, 512_000);
  const internal = Number(message.internalDate || 0);
  const receivedAt = Number.isFinite(internal) && internal > 0 ? new Date(internal).toISOString() : new Date().toISOString();
  return {
    gmailMessageId: String(message.id || ""),
    sender: (headers.from || "").slice(0, 512),
    subject: (headers.subject || "").slice(0, 998),
    body,
    receivedAt,
    attachments,
  };
}
