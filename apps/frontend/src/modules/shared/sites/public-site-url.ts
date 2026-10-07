import type { SiteDomain } from "@saas-core/api-client";

/**
 * Where a site answers for its readers: the address the panel opens it at.
 * The canonical verified domain, else the platform subdomain, else any
 * verified one; a panel opened on `.localhost` prefers the site's
 * `.localhost` subdomain and keeps the panel's port. Null while no domain is
 * verified.
 */
export function publicSiteUrl(domains: SiteDomain[]) {
  const controlHostname =
    typeof window !== "undefined" ? window.location.hostname : "";
  const localControl =
    controlHostname === "localhost" || controlHostname.endsWith(".localhost");
  const localPlatformDomain = domains.find(
    (item) =>
      item.status === "verified" &&
      item.kind === "platform" &&
      item.hostname.endsWith(".localhost"),
  );
  const domain =
    (localControl ? localPlatformDomain : undefined) ??
    domains.find((item) => item.status === "verified" && item.is_canonical) ??
    domains.find(
      (item) => item.status === "verified" && item.kind === "platform",
    ) ??
    domains.find((item) => item.status === "verified");
  if (!domain) return null;

  const local =
    domain.hostname === "localhost" || domain.hostname.endsWith(".localhost");
  const port =
    local && typeof window !== "undefined" ? window.location.port : "";
  return `${local ? "http" : "https"}://${domain.hostname}${
    port ? `:${port}` : ""
  }`;
}
