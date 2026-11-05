import JSZip from "jszip";

const UNSAFE = /[^A-Za-z0-9._ -]/g;

export function sanitizeFilename(filename: string): string {
  let name = (filename || "").replace(/\\/g, "/").split("/").pop() || "";
  name = name.replace(/\u0000/g, "").normalize("NFKC");
  name = name.replace(UNSAFE, "_").replace(/^[ .]+|[ .]+$/g, "");
  if (!name || name === "." || name === "..") return "attachment";
  if (name.length > 180) {
    const dot = name.lastIndexOf(".");
    const ext = dot > 0 ? name.slice(dot + 1) : "";
    if (ext && ext.length <= 10) name = `${name.slice(0, dot).slice(0, 160)}.${ext}`;
    else name = name.slice(0, 180);
  }
  return name || "attachment";
}

export function normalizeMime(mimeType: string): string {
  return (mimeType || "").split(";", 1)[0].trim().toLowerCase();
}

export function validateAttachment(input: {
  filename: string;
  mimeType: string;
  size: number | null;
  allowedMimes: Set<string>;
  maxBytes: number;
}): { ok: boolean; filename: string; reason?: string } {
  const filename = sanitizeFilename(input.filename);
  if (filename.includes("/") || filename.includes("\\")) {
    return { ok: false, filename: "attachment", reason: "filename is not allowed" };
  }
  const mime = normalizeMime(input.mimeType);
  if (input.size !== null && input.size > input.maxBytes) {
    return { ok: false, filename, reason: "attachment exceeds size limit" };
  }
  if (!input.allowedMimes.has(mime)) {
    return { ok: false, filename, reason: "mime type is not allowed" };
  }
  return { ok: true, filename };
}

export const FOLDER_NAMES: Record<string, string> = {
  pdf: "PDFs",
  presentation: "Presentations",
  image: "Images",
  sheet: "Sheets",
  document: "Documents",
  other: "Other",
};

const MIME_KIND: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.ms-powerpoint": "presentation",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
  "image/png": "image",
  "image/jpeg": "image",
  "image/gif": "image",
  "image/webp": "image",
  "text/csv": "sheet",
  "application/vnd.ms-excel": "sheet",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "sheet",
  "text/plain": "document",
  "application/msword": "document",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
};

const EXTENSION_KIND: Record<string, string> = {
  pdf: "pdf",
  ppt: "presentation",
  pptx: "presentation",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  csv: "sheet",
  xls: "sheet",
  xlsx: "sheet",
  txt: "document",
  doc: "document",
  docx: "document",
};

export function folderFor(kind: string): string {
  return FOLDER_NAMES[kind] || FOLDER_NAMES.other;
}

export function classifyFile(filename: string, mimeType: string, data: Buffer): string {
  const sniffed = sniff(data);
  if (sniffed) return sniffed;
  const mimeKind = MIME_KIND[normalizeMime(mimeType)];
  if (mimeKind) return mimeKind;
  const extension = sanitizeFilename(filename).split(".").pop()?.toLowerCase() || "";
  return EXTENSION_KIND[extension] || "other";
}

function sniff(data: Buffer): string | null {
  if (data.subarray(0, 4).toString("utf8") === "%PDF") return "pdf";
  if (data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image";
  if (data.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))) return "image";
  if (data.subarray(0, 4).toString("utf8") === "GIF8") return "image";
  if (data.subarray(0, 4).toString("utf8") === "RIFF" && data.subarray(8, 12).toString("utf8") === "WEBP") return "image";
  if (data.subarray(0, 2).toString("utf8") === "PK") return sniffOffice(data);
  return null;
}

function sniffOffice(data: Buffer): string | null {
  const text = data.subarray(0, Math.min(data.length, 300_000)).toString("latin1");
  if (text.includes("ppt/")) return "presentation";
  if (text.includes("xl/")) return "sheet";
  if (text.includes("word/")) return "document";
  return null;
}

export async function readExcerpt(data: Buffer, kind: string): Promise<string> {
  try {
    if (kind === "pdf") return await pdfText(data);
    if (kind === "presentation") return await zipXmlText(data, "ppt/");
    if (kind === "sheet") return data.subarray(0, 2).toString("utf8") === "PK" ? await zipXmlText(data, "xl/") : plainText(data);
    if (kind === "document") return data.subarray(0, 2).toString("utf8") === "PK" ? await zipXmlText(data, "word/") : plainText(data);
  } catch {
    return "";
  }
  return "";
}

function plainText(data: Buffer): string {
  return data.subarray(0, 20_000).toString("utf8").replace(/\s+/g, " ").trim().slice(0, 4000);
}

async function pdfText(data: Buffer): Promise<string> {
  const { extractText, getDocumentProxy } = await import("unpdf");
  const pdf = await getDocumentProxy(new Uint8Array(data));
  const extracted = await extractText(pdf, { mergePages: false });
  const pages = Array.isArray(extracted.text) ? extracted.text.slice(0, 5) : [String(extracted.text || "")];
  return pages.join(" ").replace(/\s+/g, " ").trim().slice(0, 4000);
}

async function zipXmlText(data: Buffer, prefix: string): Promise<string> {
  const zip = await JSZip.loadAsync(data);
  const chunks: string[] = [];
  let total = 0;
  const files = Object.values(zip.files).slice(0, 30);
  for (const file of files) {
    if (file.dir || !file.name.startsWith(prefix) || !file.name.endsWith(".xml")) continue;
    const raw = await file.async("string");
    const text = raw.slice(0, 200_000).replace(/<[^>]+>/g, " ");
    chunks.push(text);
    total += text.length;
    if (total >= 4000) break;
  }
  return chunks.join(" ").replace(/\s+/g, " ").trim().slice(0, 4000);
}
