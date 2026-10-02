import type { ProductCopy } from "./content";

export type MarketingLink = {
  href: string;
  label: string;
  /**
   * Followed as a full page load, not a client-side transition. Caddy grants
   * `geolocation=(self)` only to the response for `/katalog*` (ADR-064 §7),
   * and the browser keeps the policy of the document it loaded: arriving at
   * the catalogue from another page without a new request leaves "Blisko mnie"
   * blocked. Any other in-app link to the catalogue needs the same.
   */
  document?: boolean;
};

/**
 * The marketing site's main links, one list for the header and the footer.
 *
 * The company catalogue sits in it like any other page of the product's site
 * (decision 24, 2026-10-02): a product that composes profiles has a catalogue,
 * and a visitor reaches it from the menu rather than by knowing its address.
 */
export function marketingLinks(
  copy: ProductCopy,
  labels: {
    features: string;
    catalog: string;
    pricing: string;
    contact: string;
  },
  { catalog }: { catalog: boolean },
): MarketingLink[] {
  return [
    ...(copy.pages?.length
      ? copy.pages.map((page) => ({
          href: `/${page.slug}`,
          label: page.navLabel,
        }))
      : [{ href: "/#features", label: labels.features }]),
    ...(catalog
      ? [{ href: "/katalog", label: labels.catalog, document: true }]
      : []),
    { href: "/pricing", label: labels.pricing },
    { href: "/contact", label: labels.contact },
  ];
}

/**
 * Where the header shows its links inline instead of under "Menu". Beside the
 * brand and the account buttons, five links fit from `lg` (1024 px); six —
 * MedPlano's three product pages, the catalogue, pricing and contact — wrap
 * there and need `xl`.
 */
export function inlineNavFrom(links: readonly MarketingLink[]): "lg" | "xl" {
  return links.length <= 5 ? "lg" : "xl";
}
