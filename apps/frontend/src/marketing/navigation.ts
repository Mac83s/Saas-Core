import type { ProductCopy } from "./content";

export type MarketingLink = { href: string; label: string };

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
    ...(catalog ? [{ href: "/katalog", label: labels.catalog }] : []),
    { href: "/pricing", label: labels.pricing },
    { href: "/contact", label: labels.contact },
  ];
}
