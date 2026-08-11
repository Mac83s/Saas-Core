export function normalizeRequestHostname(authority: string | null): string {
  const normalizedAuthority = authority?.trim();
  if (!normalizedAuthority) return "";
  if (/[\\/@?#\s]/.test(normalizedAuthority)) return "";
  try {
    return new URL(`http://${normalizedAuthority}`).hostname
      .toLowerCase()
      .replace(/\.$/, "");
  } catch {
    return "";
  }
}
