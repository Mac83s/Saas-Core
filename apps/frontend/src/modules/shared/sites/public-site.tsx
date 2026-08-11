import type { Metadata } from "next";
import { cache } from "react";

import type { PublicSitePage } from "@saas-core/api-client";
import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedPage,
  type DesignTokensV1,
  type SiteBlock,
} from "@saas-core/site-blocks";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

export type PublicSiteResult =
  | { kind: "page"; page: PublicSitePage }
  | { kind: "redirect"; location: string }
  | { kind: "not-found" };

export const getPublicSite = cache(
  async (host: string, path: string): Promise<PublicSiteResult> => {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const url = new URL("/api/v1/public/site/", backend);
    url.searchParams.set("path", path);
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Host: host },
      redirect: "manual",
    });
    if (response.status === 308) {
      const location = response.headers.get("location");
      return location === null
        ? { kind: "not-found" }
        : { kind: "redirect", location };
    }
    if (response.status === 404) return { kind: "not-found" };
    if (!response.ok) {
      throw new Error(`Public Sites API zwróciło status ${response.status}`);
    }
    return { kind: "page", page: (await response.json()) as PublicSitePage };
  },
);

export function publicSiteMetadata(page: PublicSitePage): Metadata {
  return {
    title: page.title,
    description: page.description,
    alternates: {
      canonical: page.canonical_url,
      languages: { ...page.hreflang, "x-default": page.x_default },
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
    },
    registry,
  );
}
