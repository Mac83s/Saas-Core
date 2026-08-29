import type { Metadata } from "next";
import { cache } from "react";
import { request as httpRequest } from "node:http";

import type { PublicSitePage } from "@saas-core/api-client";
import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedPage,
  type DesignTokensV1,
  type IndexPagination,
  type SiteBlock,
} from "@saas-core/site-blocks";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

export type PublicSiteResult =
  | { kind: "page"; page: PublicSitePage }
  | { kind: "redirect"; location: string }
  | { kind: "not-found" };

type BackendResponse = {
  status: number;
  location: string | null;
  body: string;
};

/** `fetch` cannot send this request: `Host` is a forbidden header name, so
 *  undici silently replaces it with the upstream's own address and the backend
 *  resolves the wrong site — in practice, no site at all. The visitor's host is
 *  the entire routing key for a published page, so it has to arrive intact, and
 *  `node:http` is what still lets us set it. */
function requestBackend(url: URL, host: string): Promise<BackendResponse> {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method: "GET",
        headers: { host, accept: "application/json" },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode ?? 0,
            location: (response.headers.location as string | undefined) ?? null,
            body: Buffer.concat(chunks).toString("utf8"),
          }),
        );
      },
    );
    request.on("error", reject);
    request.end();
  });
}

export const getPublicSite = cache(
  async (host: string, path: string): Promise<PublicSiteResult> => {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const url = new URL("/api/v1/public/site/", backend);
    url.searchParams.set("path", path);
    const response = await requestBackend(url, host);
    if (response.status === 308) {
      return response.location === null
        ? { kind: "not-found" }
        : { kind: "redirect", location: response.location };
    }
    if (response.status === 404) return { kind: "not-found" };
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Public Sites API zwróciło status ${response.status}`);
    }
    return { kind: "page", page: JSON.parse(response.body) as PublicSitePage };
  },
);

export function publicSiteMetadata(page: PublicSitePage): Metadata {
  return {
    title: page.title,
    description: page.description,
    alternates: {
      canonical: page.canonical_url,
      languages: { ...page.hreflang, "x-default": page.x_default },
      // Without these a reader's browser has no way to find either feed: the
      // addresses exist, and nothing on the page says so.
      types: {
        "application/rss+xml": [
          {
            url: new URL("/rss.xml", page.canonical_url).toString(),
            title: page.title,
          },
        ],
        "application/atom+xml": [
          {
            url: new URL("/atom.xml", page.canonical_url).toString(),
            title: page.title,
          },
        ],
      },
    },
    openGraph: {
      title: page.social_title || page.title,
      description: page.social_description || page.description,
      url: page.canonical_url,
    },
  };
}

export function PublicSiteRenderer({ page }: { page: PublicSitePage }) {
  return renderPublishedPage(
    {
      kind: "publication",
      publicationId: page.publication_id,
      snapshotHash: page.snapshot_hash,
      blocks: page.blocks as unknown as SiteBlock[],
      designTokens: page.design_tokens as DesignTokensV1,
      navigation: page.navigation,
      // The visitor is reading one language; the menu's accessible name has to
      // be in it too, not in the panel's language.
      navigationLabel: page.locale === "en" ? "Menu" : "Menu witryny",
      pagination: page.pagination as IndexPagination | null,
      paginationLabels:
        page.locale === "en"
          ? {
              label: "Pages",
              previous: "Previous",
              next: "Next",
              position: (current, total) => `Page ${current} of ${total}`,
            }
          : {
              label: "Strony",
              previous: "Poprzednia",
              next: "Następna",
              position: (current, total) => `Strona ${current} z ${total}`,
            },
    },
    registry,
  );
}
