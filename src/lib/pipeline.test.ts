import { describe, expect, it } from "vitest";
import JSZip from "jszip";

import { classifyFile, folderFor, readExcerpt, sanitizeFilename } from "./files";
import { contentHashQuery, nameInFolderQuery } from "./google";
import { readSession, signSession } from "./session";
import { messageMatches } from "./trigger";

describe("keyword matching", () => {
  it("matches both spaced and unspaced forms", () => {
    expect(messageMatches("Please file this", "backoffice packet", ["back office", "backoffice"])).toBe("backoffice");
    expect(messageMatches("Back Office invoice", "", ["back office", "backoffice"])).toBe("back office");
    expect(messageMatches("back officer", "", ["back office"])).toBeNull();
  });
});

describe("filing", () => {
  it("uses file bytes instead of a misleading name", async () => {
    const png = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(16)]);
    expect(classifyFile("invoice.pdf", "application/pdf", png)).toBe("image");
    expect(folderFor("image")).toBe("Images");
    const zip = new JSZip();
    zip.file("ppt/slides/slide1.xml", "<a:t>Quarterly board report</a:t>");
    const data = await zip.generateAsync({ type: "nodebuffer" });
    expect(classifyFile("deck.bin", "application/octet-stream", data)).toBe("presentation");
    expect(await readExcerpt(data, "presentation")).toContain("Quarterly board report");
    expect(sanitizeFilename("../../secret.exe")).toBe("secret.exe");
  });
});

describe("drive copies", () => {
  it("treats the same name or the same bytes as one file", () => {
    const digest = "ab".repeat(32);
    expect(nameInFolderQuery("folder123", "24hrs at NTNU.pdf")).toBe(
      "name = '24hrs at NTNU.pdf' and 'folder123' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
    );
    expect(nameInFolderQuery("folder123", "it's.pdf")).toContain("it\\'s.pdf");
    expect(contentHashQuery(digest)).toBe(
      `appProperties has { key = 'bo_sha256' and value = '${digest}' } and trashed = false`,
    );
  });
});

describe("session", () => {
  it("rejects a tampered cookie", () => {
    const secret = "a".repeat(32);
    const token = signSession("admin", secret);
    expect(readSession(token, secret)).toBe("admin");
    expect(readSession(token, "b".repeat(32))).toBeNull();
  });
});
