export function messageMatches(subject: string, body: string, keywords: string[]): string | null {
  const haystack = `${subject || ""}\n${body || ""}`;
  for (const keyword of keywords) {
    const phrase = keyword.trim();
    if (!phrase) continue;
    const pattern = new RegExp(`(?<!\\w)${escapeRegExp(phrase)}(?!\\w)`, "i");
    if (pattern.test(haystack)) return phrase;
  }
  return null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
