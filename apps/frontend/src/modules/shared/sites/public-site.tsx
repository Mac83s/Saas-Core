import type { Metadata } from "next";
import { cache } from "react";
import { request as httpRequest } from "node:http";

import type { PublicSitePage } from "@saas-core/api-client";
import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedPage,
  parseSiteAppearance,
  siteUiTexts,
  type DesignTokensV1,
  type IndexPagination,
  type PagePresentationV1,
  type SiteBlock,
} from "@saas-core/site-blocks";

import { PublicContactForm } from "./public-contact-form";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

export type PublicSiteResult =
  | { kind: "page"; page: PublicSitePage }
  | { kind: "redirect"; location: string; temporary?: boolean }
  /** On a known site, the language the address was asked in and its home. */
  | { kind: "not-found"; locale?: string; homePath?: string };

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
function requestBackend(
  url: URL,
  host: string,
  countView: boolean,
): Promise<BackendResponse> {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method: "GET",
        headers: {
          host,
          accept: "application/json",
          // The renderer's verdict, never the visitor's own headers (ADR-060).
          ...(countView ? { "x-saas-core-count-view": "1" } : {}),
        },
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

/** The address as the visitor typed it: decoded segments, and the trailing
 *  slash the route params drop (the proxy reports it). The layout and the
 *  metadata build it the same way, so all three ask `getPublicSite` the same
 *  question and share one backend call — and one counted view. */
export function publicSitePath(
  segments: readonly string[] | undefined,
  trailingSlash = false,
): string {
  const path = `/${(segments ?? []).filter(Boolean).join("/")}`;
  return trailingSlash && path !== "/" ? `${path}/` : path;
}

/** `countView` is part of the cached question on purpose: every caller in one
 *  request passes the same answer, so it never splits the shared call. */
export const getPublicSite = cache(
  async (
    host: string,
    path: string,
    countView = false,
  ): Promise<PublicSiteResult> => {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const url = new URL("/api/v1/public/site/", backend);
    url.searchParams.set("path", path);
    const response = await requestBackend(url, host, countView);
    if (response.status === 308 || response.status === 307) {
      // 307: a language version withheld for a while (ADR-070 pkt 10), so a
      // search engine keeps the address.
      return response.location === null
        ? { kind: "not-found" }
        : {
            kind: "redirect",
            location: response.location,
            temporary: response.status === 307,
          };
    }
    if (response.status === 404) return notFoundOf(response.body);
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Public Sites API zwróciło status ${response.status}`);
    }
    return { kind: "page", page: JSON.parse(response.body) as PublicSitePage };
  },
);

function notFoundOf(body: string): PublicSiteResult {
  try {
    const problem = JSON.parse(body) as {
      locale?: unknown;
      home_path?: unknown;
    };
    return {
      kind: "not-found",
      ...(typeof problem.locale === "string" ? { locale: problem.locale } : {}),
      ...(typeof problem.home_path === "string"
        ? { homePath: problem.home_path }
        : {}),
    };
  } catch {
    return { kind: "not-found" };
  }
}

/** What `article` carries for an entry (`null` on every other page). */
interface PublishedArticle {
  readonly author_name?: string;
  readonly published_at?: string | null;
  readonly updated_at?: string;
  readonly tags?: readonly { readonly name?: string }[];
}

export function publicSiteMetadata(page: PublicSitePage): Metadata {
  const article = page.article as PublishedArticle | null;
  const image = page.social.image;
  const images = image ? [{ url: image.url, alt: image.alt }] : undefined;
  const shared = {
    title: page.social_title || page.title,
    description: page.social_description || page.description,
    url: page.canonical_url,
    siteName: page.social.site_name || undefined,
    locale: page.social.locale,
    alternateLocale: page.social.alternate_locales,
    images,
  };
  return {
    title: page.title,
    description: page.description,
    alternates: {
      canonical: page.canonical_url,
      languages: { ...page.hreflang, "x-default": page.x_default },
      // Without these a reader's browser has no way to find either feed: the
      // addresses exist, and nothing on the page says so. Only the feeds of
      // the page's own language (TL14).
      types: {
        "application/rss+xml": [{ url: page.feeds.rss, title: page.title }],
        "application/atom+xml": [{ url: page.feeds.atom, title: page.title }],
      },
    },
    // Where a link to the page is shared: its language and the other ones it
    // is in, the site's name, its first picture, and for an article who wrote
    // it and when (TL14).
    openGraph: article
      ? {
          ...shared,
          type: "article",
          publishedTime: article.published_at ?? undefined,
          modifiedTime: article.updated_at,
          authors: article.author_name ? [article.author_name] : undefined,
          tags: (article.tags ?? []).flatMap((tag) => (tag.name ? [tag.name] : [])),
        }
      : { ...shared, type: "website" },
    twitter: {
      card: image ? "summary_large_image" : "summary",
      title: shared.title,
      description: shared.description,
      images,
    },
    // In the document, not only by staying out of the sitemap: a crawler
    // that follows a link never reads the sitemap.
    ...(page.noindex ? { robots: { index: false, follow: true } } : {}),
  };
}

export function PublicSiteRenderer({ page }: { page: PublicSitePage }) {
  const texts = siteUiTexts(page.locale);
  return renderPublishedPage(
    {
      kind: "publication",
      locale: page.locale,
      publicationId: page.publication_id,
      snapshotHash: page.snapshot_hash,
      blocks: page.blocks as unknown as SiteBlock[],
      designTokens: page.design_tokens as DesignTokensV1,
      appearance: page.appearance
        ? parseSiteAppearance(page.appearance)
        : undefined,
      // The tagline and footer texts still in the site's language (ADR-070
      // pkt 15) carry their own `lang`.
      appearanceLang: page.appearance_lang,
      // Null for entries, blog indexes and tag pages: they have no own look.
      pagePresentation: (page.page_presentation ??
        null) as PagePresentationV1 | null,
      navigation: page.navigation,
      // AI images get the visible badge; empty when the operator hid it.
      aiMediaIds: page.ai_media_ids,
      // The visitor is reading one language; what the site says by itself —
      // the menu's name, pagination, the language switch — is in it too, not in
      // the panel's language (TL14).
      navigationLabel: texts.menu,
      pagination: page.pagination as IndexPagination | null,
      paginationLabels: texts.pagination,
      languageLinks: page.language_links,
    },
    registry,
    (form, blockPosition) => (
      <PublicContactForm
        publicationId={page.publication_id}
        path={new URL(page.canonical_url).pathname}
        blockPosition={blockPosition}
        locale={page.locale}
        contact={form.contact}
        submitLabel={form.submit_label}
        successMessage={form.success_message}
      />
    ),
  );
}
