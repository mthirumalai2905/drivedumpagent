import { createHmac, randomBytes, timingSafeEqual, createHash } from "crypto";

const TTL_SECONDS = 12 * 60 * 60;

export function secretsEqual(left: string, right: string): boolean {
  const a = createHash("sha256").update(left).digest();
  const b = createHash("sha256").update(right).digest();
  return timingSafeEqual(a, b);
}

export function signSession(username: string, secret: string, now = Math.floor(Date.now() / 1000)): string {
  const expires = now + TTL_SECONDS;
  const payload = `v1|${username}|${expires}`;
  const signature = createHmac("sha256", secret).update(payload).digest("hex");
  return Buffer.from(`${payload}|${signature}`, "utf8").toString("base64url");
}

export function readSession(token: string | undefined, secret: string, now = Math.floor(Date.now() / 1000)): string | null {
  if (!token) return null;
  try {
    const decoded = Buffer.from(token, "base64url").toString("utf8");
    const [version, username, expiresRaw, signature] = decoded.split("|");
    if (version !== "v1" || !username || !expiresRaw || !signature) return null;
    const payload = `${version}|${username}|${expiresRaw}`;
    const expected = createHmac("sha256", secret).update(payload).digest("hex");
    const left = Buffer.from(expected);
    const right = Buffer.from(signature);
    if (left.length !== right.length || !timingSafeEqual(left, right)) return null;
    if (Number(expiresRaw) < now) return null;
    return username;
  } catch {
    return null;
  }
}

export function makeOauthState(secret: string): string {
  const nonce = randomBytes(16).toString("hex");
  const issued = Math.floor(Date.now() / 1000);
  const payload = `${nonce}|${issued}`;
  const signature = createHmac("sha256", secret).update(payload).digest("hex");
  return Buffer.from(`${payload}|${signature}`, "utf8").toString("base64url");
}

export function oauthStateValid(token: string, secret: string): boolean {
  try {
    const decoded = Buffer.from(token, "base64url").toString("utf8");
    const [nonce, issuedRaw, signature] = decoded.split("|");
    if (!nonce || !issuedRaw || !signature) return false;
    const payload = `${nonce}|${issuedRaw}`;
    const expected = createHmac("sha256", secret).update(payload).digest("hex");
    const left = Buffer.from(expected);
    const right = Buffer.from(signature);
    if (left.length !== right.length || !timingSafeEqual(left, right)) return false;
    const issued = Number(issuedRaw);
    const now = Math.floor(Date.now() / 1000);
    return now - issued >= 0 && now - issued < 600;
  } catch {
    return false;
  }
}

export const SESSION_COOKIE = "bo_session";
export const SESSION_MAX_AGE = TTL_SECONDS;
