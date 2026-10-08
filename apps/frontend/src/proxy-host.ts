import { deployment } from "./generated/deployment";

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

/** Next wants an absolute Location from a proxy; on the visitor's own host
 *  and the scheme the gateway saw, so a redirect stays on their port. */
export function absoluteUrl(
  request: { headers: Headers; nextUrl: { host: string } },
  path: string,
): URL {
  const scheme =
    request.headers.get("x-forwarded-proto") === "https" ? "https" : "http";
  return new URL(
    path,
    `${scheme}://${request.headers.get("host") ?? request.nextUrl.host}`,
  );
}

/** Whether a normalized hostname is the platform's own — where the panel,
 *  the guests' pages and a product's public pages are — and not a company's
 *  site, which the proxy hands to the renderer. */
export function isControlHostname(hostname: string): boolean {
  const configured = (process.env.FRONTEND_CONTROL_HOSTS ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase().replace(/\.$/, ""))
    .filter(Boolean);
  return new Set([
    "localhost",
    "127.0.0.1",
    deployment.product.platformDomain.toLowerCase(),
    ...configured,
  ]).has(hostname);
}
