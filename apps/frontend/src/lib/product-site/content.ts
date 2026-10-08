import "server-only";

import type {
  PublicContentEntry,
  PublicContentEntryAnswer,
  PublicContentList,
  PublicContentListAnswer,
  PublicContentSitemap,
  PublicContentTerms,
  PublicContentType,
} from "@saas-core/api-client";

import type { SiteSitemapEntry, SiteVersions } from "#lib/product-site/table";

/**
 * The platform's own published content for a product's public pages
 * (ADR-079 pkt 30–32; contract: `docs/architecture/product-content-read.md`).
 *
 * The platform writes its content — a guide, a blog — in its workspace's
 * panel; the product's coded pages (ADR-080) read here what is published
 * and draw it inside their own layout. Server side only, at request time:
 * the backend is asked directly, as the other server reads are.
 *
 * Everything comes back as **address parts** — a type's key, a language, a
 * slug — never as a path. The product's own table makes addresses of them
 * (`siteHref`, `siteMetadata`, `siteVersions`), so an address cannot be
 * written differently from how the proxy resolves it.
 */

/** An entry asked by its address parts. */
export type ContentEntryResult =
  | { kind: "entry"; entry: PublicContentEntry }
  /** It answers elsewhere now: one 308 to the address of these parts. */
  | { kind: "moved"; to: { type: string; locale: string; slug: string } }
  /** Nothing published is there — the page answers `notFound()`. */
  | { kind: "not-found" };

/** A page of a type's list, or of one term's. */
export type ContentListResult =
  | { kind: "list"; list: PublicContentList }
  | {
      kind: "moved";
      to: {
        type: string;
        locale: string;
        taxonomy: string | null;
        term: string | null;
      };
    }
  | { kind: "not-found" };

type Query = Record<string, string | number | undefined>;

async function read<T>(path: string, query: Query = {}): Promise<T | null> {
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const url = new URL(`/api/v1/public/content/${path}`, backend);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  // Never cached here: what is published is what is read. A page that wants
  // to be rebuilt less often says so itself (`revalidate`).
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Public content API answered ${response.status}`);
  }
  return (await response.json()) as T;
}

const part = encodeURIComponent;

/**
 * A published entry by type, language and slug. `canonicalUrl` — the full
 * address the product gives the entry — also asks for the entry's own
 * JSON-LD nodes (`entry.structured_data`).
 */
export async function contentEntry(args: {
  type: string;
  locale: string;
  slug: string;
  canonicalUrl?: string;
}): Promise<ContentEntryResult> {
  const answer = await read<PublicContentEntryAnswer>(
    `types/${part(args.type)}/entries/${part(args.locale)}/${part(args.slug)}/`,
    { canonical_url: args.canonicalUrl },
  );
  if (answer?.moved) return { kind: "moved", to: answer.moved };
  if (answer?.entry) return { kind: "entry", entry: answer.entry };
  return { kind: "not-found" };
}

/**
 * A page of a type's published entries in a language, newest first — all of
 * them, or those under one term (`taxonomy` and `term` together).
 */
export async function contentEntries(args: {
  type: string;
  locale: string;
  page?: number;
  pageSize?: number;
  taxonomy?: string;
  term?: string;
}): Promise<ContentListResult> {
  const answer = await read<PublicContentListAnswer>(
    `types/${part(args.type)}/entries/`,
    {
      locale: args.locale,
      page: args.page,
      page_size: args.pageSize,
      taxonomy: args.taxonomy,
      term: args.term,
    },
  );
  if (answer?.moved) return { kind: "moved", to: answer.moved };
  if (answer?.list) return { kind: "list", list: answer.list };
  return { kind: "not-found" };
}

/** The types that have something published; none where the deployment has
 *  no publisher. */
export async function contentTypes(): Promise<PublicContentType[]> {
  return (await read<PublicContentType[]>("types/")) ?? [];
}

/** A type's terms in a language, with how many listed entries each has;
 *  `null` where the type has no list in that language. */
export async function contentTerms(args: {
  type: string;
  locale: string;
}): Promise<PublicContentTerms | null> {
  return read<PublicContentTerms>(`types/${part(args.type)}/terms/`, {
    locale: args.locale,
  });
}

/** Everything of the platform's content a sitemap lists, as address parts. */
export async function contentSitemap(): Promise<PublicContentSitemap> {
  return (
    (await read<PublicContentSitemap>("sitemap/")) ?? {
      entries: [],
      lists: [],
      terms: [],
    }
  );
}

/**
 * An entry's language versions as the table takes them: `{ pl: { slug: … },
 * en: { slug: … } }` for `siteMetadata` and `siteVersions` — hreflang and
 * the language switch then name exactly the versions that are published.
 * `param` is the name of the page file's parameter (`[slug]`).
 */
export function contentVersions(
  versions: readonly { locale: string; slug?: string }[],
  param = "slug",
): SiteVersions {
  return Object.fromEntries(
    versions.map((version) => [
      version.locale,
      version.slug === undefined ? {} : { [param]: version.slug },
    ]),
  );
}

/** Which page of the product's table shows what, for one content type. */
export type ContentRoutes = {
  /** The entry's page, with one parameter: `/guide/[slug]`. */
  entry?: string;
  /** The type's own list: `/guide`. */
  list?: string;
  /** A term's list per taxonomy, with one parameter:
   *  `{ tag: "/guide/tag/[term]" }`. */
  terms?: Readonly<Record<string, string>>;
};

const parameter = (route: string) => /\[([^\]]+)\]/.exec(route)?.[1] ?? "slug";

const newest = (versions: readonly { updated_at: string }[]) =>
  versions
    .map((version) => version.updated_at)
    .sort()
    .at(-1);

/**
 * The platform's content as lines of the product's sitemap: give each
 * content type the pages of the table that show it, and get what
 * `site-sitemap.ts` returns. A type, a list or a taxonomy without a page is
 * left out; the core writes every address and its language alternates from
 * the table, as for the product's other pages.
 */
export async function contentSitemapEntries(
  routes: Readonly<Record<string, ContentRoutes>>,
): Promise<SiteSitemapEntry[]> {
  const listing = await contentSitemap();
  // Parameters without a language would read as "the same in every
  // language of the table": an item that names none is no line at all.
  const named = <T extends { versions: readonly unknown[] }>(items: T[]) =>
    items.filter((item) => item.versions.length > 0);
  const sitemap = {
    entries: named(listing.entries),
    lists: named(listing.lists),
    terms: named(listing.terms),
  };
  const lines: SiteSitemapEntry[] = [];
  for (const item of sitemap.lists) {
    const route = routes[item.type]?.list;
    if (!route) continue;
    lines.push({
      route,
      params: contentVersions(item.versions),
      lastModified: newest(item.versions),
    });
  }
  for (const item of sitemap.entries) {
    const route = routes[item.type]?.entry;
    if (!route) continue;
    lines.push({
      route,
      params: contentVersions(item.versions, parameter(route)),
      lastModified: newest(item.versions),
    });
  }
  for (const item of sitemap.terms) {
    const route = routes[item.type]?.terms?.[item.taxonomy ?? ""];
    if (!route) continue;
    lines.push({
      route,
      params: contentVersions(item.versions, parameter(route)),
      lastModified: newest(item.versions),
    });
  }
  return lines;
}
