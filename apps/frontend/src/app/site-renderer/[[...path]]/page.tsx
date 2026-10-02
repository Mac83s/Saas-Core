import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound, permanentRedirect } from "next/navigation";

import { countsAsPageView } from "../../../modules/shared/sites/page-view";
import {
  getPublicSite,
  publicSiteMetadata,
  publicSitePath,
  PublicSiteRenderer,
} from "../../../modules/shared/sites/public-site";
import { PUBLIC_SITE_TRAILING_SLASH_HEADER } from "../../../proxy";

export const dynamic = "force-dynamic";

type PublicSiteRouteProps = {
  params: Promise<{ path?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({
  params,
}: PublicSiteRouteProps): Promise<Metadata> {
  const request = await publicRequest(params);
  const result = await getPublicSite(
    request.host,
    request.path,
    request.countView,
  );
  return result.kind === "page" ? publicSiteMetadata(result.page) : {};
}

export default async function PublicSitePage({
  params,
  searchParams,
}: PublicSiteRouteProps) {
  const request = await publicRequest(params);
  const result = await getPublicSite(
    request.host,
    request.path,
    request.countView,
  );
  if (result.kind === "not-found") notFound();
  if (result.kind === "redirect") {
    permanentRedirect(withSearchParams(result.location, await searchParams));
  }
  return <PublicSiteRenderer page={result.page} />;
}

function withSearchParams(
  location: string,
  values: Record<string, string | string[] | undefined>,
): string {
  const target = new URL(location);
  for (const [key, rawValue] of Object.entries(values)) {
    for (const value of Array.isArray(rawValue) ? rawValue : [rawValue]) {
      if (value !== undefined) target.searchParams.append(key, value);
    }
  }
  return target.toString();
}

async function publicRequest(params: PublicSiteRouteProps["params"]) {
  const [requestHeaders, route] = await Promise.all([headers(), params]);
  const host = requestHeaders.get("host") ?? "";
  const path = publicSitePath(
    route.path,
    requestHeaders.get(PUBLIC_SITE_TRAILING_SLASH_HEADER) === "1",
  );
  return { host, path, countView: countsAsPageView(requestHeaders) };
}
