/**
 * A product's public pages on its own host (ADR-080): the one table of their
 * addresses, compiled. What routes a visit (`match`) and what writes a link,
 * a canonical, an hreflang or a sitemap line (`href`, `versions`) are two
 * readings of the same compiled rows, so they cannot disagree; a table that
 * could answer one address twice, or send a visitor through two redirects, is
 * refused here, when it is compiled, not found by a visitor.
 *
 * Pure: no profile, no request, no React — the proxy, the server and the
 * browser all read it. The contract is `docs/architecture/product-public-site.md`.
 */

/**
 * The folder of the product's page files: `src/app/product-site/[locale]`.
 * Beside `app/[locale]`, not under it, so the pages have a root layout of
 * the product's own and ship its words, not the panel's whole catalogue.
 */
export const SITE_PAGES_SEGMENT = "product-site";
/** Where an address nobody claims is sent, for the product's own 404. */
export const SITE_UNCLAIMED_PATH = "/_unclaimed";

/** A page's parameters: `{ slug: "labrador" }`. */
export type SiteParams = Readonly<Record<string, string>>;
/** A page's parameters per language; a language left out has no such page. */
export type SiteVersions = Readonly<Partial<Record<string, SiteParams>>>;

/**
 * The slot `src/product/public-site.ts`. A key is the page file's path under
 * the product's folder, as Next spells it (`/`, `/breeds`, `/breeds/[slug]`);
 * its value is the address visitors use — one string for every content
 * language of the profile, or one per language (a language left out has no
 * such page). The default language's address has no prefix, the others get
 * `/<language>` in front; neither is written in the table.
 */
export type ProductPublicSite = {
  routes: Readonly<
    Record<string, string | Readonly<Partial<Record<string, string>>>>
  >;
};

/**
 * The slot `src/product/old-addresses.ts`: addresses of the site this one
 * replaces. `moved` answers one 308 to an address of the table; `gone`
 * answers 410. Sources are whole paths as the old site had them, language
 * prefix included.
 */
export type ProductOldAddresses = {
  moved?: Readonly<Record<string, string>>;
  gone?: readonly string[];
};

/**
 * One line of the slot `src/product/site-sitemap.ts`: a page of the table
 * that exists, never an address. `params` as for `versions` — the same in
 * every language, or per language where the page's own name is translated.
 */
export type SiteSitemapEntry = {
  route: string;
  params?: SiteParams | SiteVersions;
  lastModified?: string | Date;
};

/** The slot `src/product/site-messages.ts`: content language → messages. */
export type SiteMessages = Readonly<
  Partial<Record<string, Record<string, unknown>>>
>;

/** First segments that are not the product's to name. */
export type ReservedSegments = {
  /** The panel's, a guest's and the platform's own. */
  exact: ReadonlySet<string>;
  /** What never reaches the proxy at all: its matcher skips these prefixes. */
  prefixes: readonly string[];
};

export type SiteOptions = {
  /** The profile's content languages; the table's other languages are left out. */
  locales: readonly string[];
  /** The language whose addresses have no prefix. */
  defaultLocale: string;
  reserved: ReservedSegments;
};

export type SiteMatch =
  | {
      kind: "page";
      route: string;
      locale: string;
      params: SiteParams;
      /** The page file's path with the parameters filled in. */
      page: string;
    }
  /** The default language spelled with its prefix: one 308 to `path`. */
  | { kind: "canonical"; path: string };

export type SiteVersion = { locale: string; path: string };

export type CompiledSite = {
  /**
   * The same table as if the profile offered every language it names. A list
   * of old addresses is checked against this one, so it is right or wrong
   * whichever profile compiles it; a profile then serves the rules that lead
   * into its own languages.
   */
  declared: CompiledSite;
  /** The languages the product's pages may speak, in the profile's order. */
  locales: readonly string[];
  defaultLocale: string;
  /** The table's keys. */
  routes: readonly string[];
  /**
   * Whether the page has an address — in that language, or without one in
   * any language the profile serves. Never throws: the question a menu entry
   * or a button asks before it links to a page the table may not name yet.
   */
  has(route: string, locale?: string): boolean;
  /** The languages a page has an address in. Throws for a page the table
   *  does not name — ask `has` first where that may be. */
  languages(route: string): readonly string[];
  /** Whether the page's address takes parameters. */
  hasParams(route: string): boolean;
  /**
   * The page an address is, spelled exactly: lower case, no trailing slash,
   * nothing percent-encoded. Any other spelling is not an address of the
   * table (`null`) — it gets the 404, not a redirect.
   */
  match(pathname: string): SiteMatch | null;
  /** The address of a page in a language. Throws for one the table has not. */
  href(route: string, locale: string, params?: SiteParams): string;
  /**
   * A page's address in each language it exists in — the language switch,
   * hreflang, the sitemap. `params` are the same in every language, or given
   * per language where the page's own name is translated; a language without
   * parameters, or with ones that cannot be an address, is left out.
   */
  versions(route: string, params?: SiteParams | SiteVersions): SiteVersion[];
};

export type OldAddress =
  | { kind: "moved"; to: string }
  /** `locale`: the language the address was asked in, for the 410's words. */
  | { kind: "gone"; locale: string };

export type CompiledOldAddresses = {
  /** The rules this profile answers. */
  size: number;
  /** The rules left out here: they lead into a language the profile lacks. */
  unserved: number;
  /** The rule of a visitor's path as the URL carries it, if any. */
  lookup(pathname: string): OldAddress | null;
  /** Each rule's source as compared, for a check that walks all of them. */
  sources(): readonly string[];
};

/** A table that cannot be served as written. */
export class ProductSiteError extends Error {
  constructor(message: string) {
    super(`product public site: ${message}`);
    this.name = "ProductSiteError";
  }
}

/** Latin letters, digits and single hyphens between them. */
const SEGMENT = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const PARAM = /^\[([a-z][A-Za-z0-9]*)\]$/;
const LANGUAGE = /^[a-z]{2}$/;

type Part = { text: string } | { param: string };
type Row = { route: string; page: Part[]; address: Part[] };

const isParam = (part: Part): part is { param: string } => "param" in part;

function parse(template: string, what: string): Part[] {
  if (template === "/") return [];
  if (!template.startsWith("/") || template.endsWith("/")) {
    throw new ProductSiteError(
      `${what}: "${template}" must start with a slash and not end with one`,
    );
  }
  return template
    .slice(1)
    .split("/")
    .map((segment) => {
      const param = PARAM.exec(segment);
      if (param?.[1]) return { param: param[1] };
      if (!SEGMENT.test(segment)) {
        throw new ProductSiteError(
          `${what}: segment "${segment}" of "${template}" — a segment is a–z, 0–9 and single hyphens, or a [parameter]`,
        );
      }
      return { text: segment };
    });
}

function paramNames(parts: Part[], what: string): string[] {
  const names = parts.filter(isParam).map((part) => part.param);
  if (new Set(names).size !== names.length) {
    throw new ProductSiteError(`${what}: a parameter is named twice`);
  }
  return names.sort();
}

function fill(parts: Part[], params: SiteParams): string | null {
  const segments: string[] = [];
  for (const part of parts) {
    if (!isParam(part)) {
      segments.push(part.text);
      continue;
    }
    const value = params[part.param];
    if (typeof value !== "string" || !SEGMENT.test(value)) return null;
    segments.push(value);
  }
  return `/${segments.join("/")}`;
}

/**
 * A static segment answers before a parameter in the same place. Only rows
 * of one length ever compete for an address, so length orders first — which
 * also keeps the comparison one a sort can rely on.
 */
function bySpecificity(a: Row, b: Row): number {
  if (a.address.length !== b.address.length) {
    return a.address.length - b.address.length;
  }
  for (const [index, left] of a.address.entries()) {
    const right = b.address[index];
    if (right && isParam(left) !== isParam(right))
      return isParam(left) ? 1 : -1;
  }
  return 0;
}

function refuseReserved(
  first: string,
  named: string,
  reserved: ReservedSegments,
  what: string,
): void {
  const prefix = reserved.prefixes.find((entry) => first.startsWith(entry));
  if (prefix !== undefined) {
    throw new ProductSiteError(
      `${what}: an address starting with "${prefix}" never reaches the pages`,
    );
  }
  if (reserved.exact.has(named)) {
    throw new ProductSiteError(
      `${what}: "${named}" is the platform's own address`,
    );
  }
}

export function compileProductSite(
  definition: ProductPublicSite,
  options: SiteOptions,
): CompiledSite {
  const named = Object.values(definition.routes).flatMap((addresses) =>
    typeof addresses === "string" ? [] : Object.keys(addresses),
  );
  const every = [...new Set([...options.locales, ...named])];
  const served = build(definition, options);
  const all =
    every.length === options.locales.length
      ? served
      : build(definition, { ...options, locales: every });
  // The reading in every language declares itself.
  const declared = all as CompiledSite;
  declared.declared = declared;
  return served === all ? declared : Object.assign(served, { declared });
}

/** The table as one set of languages reads it. */
function build(
  definition: ProductPublicSite,
  options: SiteOptions,
): Omit<CompiledSite, "declared"> {
  const { locales, defaultLocale, reserved } = options;
  if (!locales.includes(defaultLocale)) {
    throw new ProductSiteError(
      `the default language "${defaultLocale}" is not a content language of the profile`,
    );
  }
  const rows = new Map<string, Row[]>(locales.map((locale) => [locale, []]));
  const byRoute = new Map<string, Map<string, Row>>();
  // Every language the table names is checked, served by this profile or not:
  // a table is right or wrong as a whole, whichever profile compiles it.
  const shapes = new Map<string, Map<string, string>>();

  for (const [route, addresses] of Object.entries(definition.routes)) {
    const page = parse(route, `page ${route}`);
    const pageParams = paramNames(page, `page ${route}`);
    const perLocale =
      typeof addresses === "string"
        ? Object.fromEntries(locales.map((locale) => [locale, addresses]))
        : addresses;
    const served = new Map<string, Row>();
    for (const [locale, template] of Object.entries(perLocale)) {
      if (template === undefined) continue;
      const what = `${route} in ${locale}`;
      if (!LANGUAGE.test(locale)) {
        throw new ProductSiteError(`${what}: "${locale}" is not a language`);
      }
      const address = parse(template, what);
      if ((address.length === 0) !== (page.length === 0)) {
        throw new ProductSiteError(
          `${what}: the address "/" and the page "/" belong to each other`,
        );
      }
      const [first] = address;
      if (first) {
        if (isParam(first)) {
          throw new ProductSiteError(
            `${what}: the first segment of "${template}" must be a name, not a parameter`,
          );
        }
        if (LANGUAGE.test(first.text)) {
          throw new ProductSiteError(
            `${what}: "${first.text}" — two letters in front are a language, today or tomorrow`,
          );
        }
        refuseReserved(first.text, first.text, reserved, what);
      }
      if (paramNames(address, what).join() !== pageParams.join()) {
        throw new ProductSiteError(
          `${what}: "${template}" must carry the parameters of the page, no more and no fewer`,
        );
      }
      const shape = address
        .map((part) => (isParam(part) ? "[]" : part.text))
        .join("/");
      const taken = shapes.get(locale) ?? new Map<string, string>();
      shapes.set(locale, taken);
      const other = taken.get(shape);
      if (other !== undefined) {
        throw new ProductSiteError(
          `${what}: "${template}" is already the address of ${other}`,
        );
      }
      taken.set(shape, route);
      if (!locales.includes(locale)) continue;
      const row = { route, page, address };
      served.set(locale, row);
      rows.get(locale)?.push(row);
    }
    byRoute.set(route, served);
  }
  for (const list of rows.values()) list.sort(bySpecificity);

  const prefix = (locale: string) =>
    locale === defaultLocale ? "" : `/${locale}`;
  const spell = (locale: string, path: string) =>
    path === "/" ? prefix(locale) || "/" : `${prefix(locale)}${path}`;

  function served(route: string): Map<string, Row> {
    const known = byRoute.get(route);
    if (!known) throw new ProductSiteError(`no page "${route}" in the table`);
    return known;
  }

  function address(
    route: string,
    locale: string,
    params: SiteParams,
  ): string | null {
    const row = served(route).get(locale);
    if (!row) return null;
    const path = fill(row.address, params);
    return path === null ? null : spell(locale, path);
  }

  const site: Omit<CompiledSite, "declared"> = {
    locales,
    defaultLocale,
    routes: [...byRoute.keys()],
    has(route, locale) {
      const known = byRoute.get(route);
      if (!known) return false;
      return locale === undefined ? known.size > 0 : known.has(locale);
    },
    languages: (route) => locales.filter((locale) => served(route).has(locale)),
    hasParams: (route) =>
      [...served(route).values()].some((row) => row.page.some(isParam)),
    match(pathname) {
      if (!pathname.startsWith("/")) return null;
      const segments = pathname === "/" ? [] : pathname.slice(1).split("/");
      const [first] = segments;
      const prefixed = first !== undefined && locales.includes(first);
      const locale = prefixed ? first : defaultLocale;
      const rest = prefixed ? segments.slice(1) : segments;
      for (const row of rows.get(locale) ?? []) {
        if (row.address.length !== rest.length) continue;
        const params: Record<string, string> = {};
        const fits = row.address.every((part, index) => {
          const segment = rest[index] ?? "";
          if (!isParam(part)) return part.text === segment;
          params[part.param] = segment;
          return SEGMENT.test(segment);
        });
        if (!fits) continue;
        if (prefixed && locale === defaultLocale) {
          return {
            kind: "canonical",
            path: `/${rest.join("/")}`,
          };
        }
        return {
          kind: "page",
          route: row.route,
          locale,
          params,
          page: fill(row.page, params) ?? "/",
        };
      }
      return null;
    },
    href(route, locale, params = {}) {
      const path = address(route, locale, params);
      if (path === null) {
        throw new ProductSiteError(
          `no address for "${route}" in ${locale} with ${JSON.stringify(params)}`,
        );
      }
      return path;
    },
    versions(route, params = {}) {
      const perLocale = Object.values(params).some(
        (value) => typeof value === "object",
      );
      return site.languages(route).flatMap((locale) => {
        const own = perLocale
          ? (params as SiteVersions)[locale]
          : (params as SiteParams);
        if (!own) return [];
        const path = address(route, locale, own);
        return path === null ? [] : [{ locale, path }];
      });
    },
  };
  return site;
}

/**
 * How an old address is compared — a rule's source when the table is
 * compiled and a visitor's path on every request, by this one function:
 * empty segments are dropped (so a trailing or doubled slash does not
 * matter), each segment is percent-decoded once, brought to Unicode NFC and
 * lower-cased. `null`: not comparable (broken encoding, or an encoded slash
 * inside a segment) — such a path matches no rule.
 */
export function normalizeOldAddress(pathname: string): string | null {
  const segments: string[] = [];
  for (const raw of pathname.split("/")) {
    if (raw === "") continue;
    let segment: string;
    try {
      segment = decodeURIComponent(raw);
    } catch {
      return null;
    }
    if (segment.includes("/")) return null;
    segments.push(segment.normalize("NFC").toLowerCase().normalize("NFC"));
  }
  return `/${segments.join("/")}`;
}

export function compileOldAddresses(
  rules: ProductOldAddresses,
  site: CompiledSite,
  reserved: ReservedSegments,
): CompiledOldAddresses {
  // Checked against every language the table names, so the verdict does not
  // depend on the profile; served from the profile's own.
  const all = site.declared;
  const sources = new Set<string>();
  const table = new Map<string, OldAddress>();

  /** The page an address is, in its canonical spelling or under the default
   *  language's prefix; `null` for an address of no page. */
  function pageAt(path: string): string | null {
    const found = all.match(path);
    if (found?.kind === "canonical") return pageAt(found.path);
    return found?.route ?? null;
  }

  function source(written: string): string {
    const what = `old address "${written}"`;
    if (!written.startsWith("/") || /[?#]/.test(written)) {
      throw new ProductSiteError(
        `${what}: a rule is a path — a leading slash, no query, no fragment`,
      );
    }
    const normalized = normalizeOldAddress(written);
    if (normalized === null) {
      throw new ProductSiteError(`${what}: cannot be decoded`);
    }
    const segments = normalized.slice(1).split("/");
    const [first = "", second = ""] = segments;
    if (first === "") {
      throw new ProductSiteError(
        `${what}: the home page is not an old address`,
      );
    }
    if (segments.some((segment) => segment.includes("."))) {
      throw new ProductSiteError(
        `${what}: an address with a dot is served as a file and never reaches the rules — redirect it in the server in front`,
      );
    }
    refuseReserved(
      first,
      LANGUAGE.test(first) ? second : first,
      reserved,
      what,
    );
    // A rule answers before the pages do, so one written over a page that
    // has no parameter would take that page away — in any language the table
    // names, and in the spelling with the default language's prefix too,
    // which is owed a redirect to the page. Over a parameter's value it is
    // the point: a renamed entry of a section.
    const route = pageAt(normalized);
    if (route !== null && !all.hasParams(route)) {
      throw new ProductSiteError(
        `${what}: it is the address of the page ${route}`,
      );
    }
    if (sources.has(normalized)) {
      throw new ProductSiteError(`${what}: declared twice`);
    }
    sources.add(normalized);
    return normalized;
  }

  for (const written of rules.gone ?? []) {
    const normalized = source(written);
    const [first = ""] = normalized.slice(1).split("/");
    table.set(normalized, {
      kind: "gone",
      locale: site.locales.includes(first) ? first : site.defaultLocale,
    });
  }
  const moved = Object.entries(rules.moved ?? {}).map(
    ([written, to]) => [written, to, source(written)] as const,
  );
  // Only once every source is known can a target be told from one.
  let unserved = 0;
  for (const [written, to, normalized] of moved) {
    const what = `old address "${written}"`;
    if (all.match(to)?.kind !== "page") {
      throw new ProductSiteError(
        `${what}: its target "${to}" is not an address of the table in its canonical spelling`,
      );
    }
    if (sources.has(normalizeOldAddress(to) ?? "")) {
      throw new ProductSiteError(
        `${what}: its target "${to}" is an old address itself — a chain or a loop`,
      );
    }
    // A right rule into a language this profile does not offer: left out
    // here, not an error — the list is one for all the product's profiles.
    if (site.match(to)?.kind === "page") {
      table.set(normalized, { kind: "moved", to });
    } else {
      unserved += 1;
    }
  }

  return {
    size: table.size,
    unserved,
    lookup(pathname) {
      const key = normalizeOldAddress(pathname);
      return key === null ? null : (table.get(key) ?? null);
    },
    sources: () => [...table.keys()],
  };
}
