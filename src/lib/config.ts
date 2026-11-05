import path from "path";

export type Settings = {
  appName: string;
  appEnv: "development" | "production" | "test";
  appSecretKey: string;
  dashboardUsername: string;
  dashboardPassword: string;
  deepseekApiKey: string;
  deepseekBaseUrl: string;
  deepseekModel: string;
  googleClientId: string;
  googleClientSecret: string;
  googleRefreshToken: string;
  googleOauthRedirectUri: string;
  googleDriveFolderId: string;
  googleGmailUser: string;
  googleDriveSupportsShared: boolean;
  keywords: string[];
  pollIntervalSeconds: number;
  pollEnabled: boolean;
  emailLookbackMinutes: number;
  maxAttachmentBytes: number;
  maxAttachmentsPerEmail: number;
  maxMessagesPerCycle: number;
  allowedMimes: Set<string>;
  databasePath: string;
  lockTtlSeconds: number;
  secureCookies: boolean;
};

const DEFAULT_MIMES = [
  "application/pdf",
  "text/plain",
  "text/csv",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "application/zip",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
  "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
  "application/vnd.openxmlformats-officedocument.presentationml.template",
  "application/vnd.oasis.opendocument.presentation",
  "application/vnd.apple.keynote",
  "video/mp4",
  "video/quicktime",
  "video/webm",
  "video/x-msvideo",
  "video/mpeg",
  "video/3gpp",
  "video/x-matroska",
  "video/ogg",
];

let cached: Settings | null = null;

function requiredText(name: string, fallback = ""): string {
  return (process.env[name] ?? fallback).trim();
}

function integer(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value)) throw new Error(`${name} must be an integer`);
  return value;
}

export function getSettings(): Settings {
  if (cached) return cached;
  const appEnv = requiredText("APP_ENV", "development").toLowerCase();
  if (appEnv !== "development" && appEnv !== "production" && appEnv !== "test") {
    throw new Error("APP_ENV must be development, production, or test");
  }
  const secret = requiredText("APP_SECRET_KEY");
  const password = requiredText("DASHBOARD_PASSWORD");
  const username = requiredText("DASHBOARD_USERNAME", "admin");
  if (secret.length < 32) {
    throw new Error("APP_SECRET_KEY must be a random string of at least 32 characters");
  }
  const minimumPassword = appEnv === "development" ? 1 : 12;
  if (password.length < minimumPassword) {
    throw new Error("DASHBOARD_PASSWORD must be at least 12 characters in production");
  }
  if (!username) throw new Error("DASHBOARD_USERNAME is required");

  const keywords = requiredText("TRIGGER_KEYWORD", "back office,backoffice")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!keywords.length) throw new Error("TRIGGER_KEYWORD must contain at least one keyword");

  const pollIntervalSeconds = integer("POLL_INTERVAL_SECONDS", 60);
  if (pollIntervalSeconds < 15 || pollIntervalSeconds > 3600) {
    throw new Error("POLL_INTERVAL_SECONDS must be between 15 and 3600");
  }
  const emailLookbackMinutes = integer("EMAIL_LOOKBACK_MINUTES", 1440);
  if (emailLookbackMinutes < 1 || emailLookbackMinutes > 1440) {
    throw new Error("EMAIL_LOOKBACK_MINUTES must be between 1 and 1440");
  }
  const maxAttachmentBytes = integer("MAX_ATTACHMENT_BYTES", 100_000_000);
  if (maxAttachmentBytes < 1 || maxAttachmentBytes > 100_000_000) {
    throw new Error("MAX_ATTACHMENT_BYTES must be between 1 and 100000000");
  }

  const deepseekBase = requiredText("DEEPSEEK_BASE_URL", "https://api.deepseek.com").replace(/\/$/, "");
  if (appEnv !== "test" && deepseekBase && !deepseekBase.startsWith("https://") && !deepseekBase.startsWith("http://127.0.0.1") && !deepseekBase.startsWith("http://localhost")) {
    throw new Error("DEEPSEEK_BASE_URL must use https, except for localhost");
  }
  let redirectUri = requiredText("GOOGLE_OAUTH_REDIRECT_URI").replace(/\/$/, "");
  const vercelHost = (process.env.VERCEL_PROJECT_PRODUCTION_URL || "").replace(/^https?:\/\//, "");
  if (process.env.VERCEL && vercelHost && (!redirectUri.startsWith("https://") || redirectUri.includes("127.0.0.1") || redirectUri.includes("localhost"))) {
    redirectUri = `https://${vercelHost}/oauth/google/callback`;
  }
  if (appEnv === "production") {
    const missing = [
      ["GOOGLE_CLIENT_ID", requiredText("GOOGLE_CLIENT_ID")],
      ["GOOGLE_CLIENT_SECRET", requiredText("GOOGLE_CLIENT_SECRET")],
      ["GOOGLE_REFRESH_TOKEN", requiredText("GOOGLE_REFRESH_TOKEN")],
      ["GOOGLE_DRIVE_FOLDER_ID", requiredText("GOOGLE_DRIVE_FOLDER_ID")],
      ["GOOGLE_GMAIL_USER", requiredText("GOOGLE_GMAIL_USER")],
      ["GOOGLE_OAUTH_REDIRECT_URI", redirectUri],
    ].filter(([, value]) => !value).map(([name]) => name);
    if (missing.length) throw new Error("Production is missing " + missing.join(", "));
    if (!redirectUri.startsWith("https://")) {
      throw new Error("GOOGLE_OAUTH_REDIRECT_URI must use https in production");
    }
  }

  const repoRoot = path.resolve(process.cwd());
  const configured = requiredText("DATABASE_URL", "sqlite:///./backoffice.db");
  let databasePath = path.join(repoRoot, "backoffice.db");
  if (configured.startsWith("sqlite:///")) {
    const raw = configured.slice("sqlite:///".length);
    databasePath = path.isAbsolute(raw) ? raw : path.resolve(repoRoot, raw.replace(/^\.\//, ""));
  } else if (appEnv === "production" && !process.env.VERCEL) {
    throw new Error("This Next.js build currently stores records in SQLite. Set DATABASE_URL to a sqlite path.");
  }
  if (process.env.VERCEL) databasePath = "/tmp/backoffice.db";

  cached = {
    appName: requiredText("APP_NAME", "Back Office"),
    appEnv,
    appSecretKey: secret,
    dashboardUsername: username,
    dashboardPassword: password,
    deepseekApiKey: requiredText("DEEPSEEK_API_KEY"),
    deepseekBaseUrl: deepseekBase,
    deepseekModel: requiredText("DEEPSEEK_MODEL"),
    googleClientId: requiredText("GOOGLE_CLIENT_ID"),
    googleClientSecret: requiredText("GOOGLE_CLIENT_SECRET"),
    googleRefreshToken: requiredText("GOOGLE_REFRESH_TOKEN"),
    googleOauthRedirectUri: redirectUri,
    googleDriveFolderId: requiredText("GOOGLE_DRIVE_FOLDER_ID"),
    googleGmailUser: requiredText("GOOGLE_GMAIL_USER", "backoffice@synx.tools"),
    googleDriveSupportsShared: requiredText("GOOGLE_DRIVE_SUPPORTS_SHARED", "false").toLowerCase() === "true",
    keywords,
    pollIntervalSeconds,
    pollEnabled: requiredText("POLL_ENABLED", "true").toLowerCase() !== "false",
    emailLookbackMinutes,
    maxAttachmentBytes,
    maxAttachmentsPerEmail: integer("MAX_ATTACHMENTS_PER_EMAIL", 20),
    maxMessagesPerCycle: integer("MAX_MESSAGES_PER_CYCLE", 100),
    allowedMimes: new Set(
      requiredText("ALLOWED_MIME_TYPES", DEFAULT_MIMES.join(","))
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    ),
    databasePath,
    lockTtlSeconds: Math.max(pollIntervalSeconds * 10, 180),
    secureCookies: appEnv === "production" || Boolean(process.env.VERCEL),
  };
  return cached;
}

export function resetSettingsForTests() {
  cached = null;
}
