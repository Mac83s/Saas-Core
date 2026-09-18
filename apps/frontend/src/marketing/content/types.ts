/**
 * The copy of a product's marketing site (ADR-048).
 *
 * Content lives here, per product and per locale, and never inside the page
 * components — so moving it to panel-edited rows later swaps the source, not
 * the pages. Interface strings shared by every product (navigation, buttons)
 * are in `messages/*.json` under `Marketing`.
 */
export type MarketingLocale = "pl" | "en";

export type ProductCopy = {
  seo: { title: string; description: string };
  hero: {
    eyebrow: string;
    headline: string;
    lead: string;
    highlights: string[];
  };
  features: {
    title: string;
    lead: string;
    items: { title: string; body: string }[];
  };
  /** Who the product is for; each gets its own column on the home page. */
  audiences: {
    title: string;
    headline: string;
    body: string;
    points: string[];
  }[];
  faq: { question: string; answer: string }[];
  pricing: {
    title: string;
    lead: string;
    note: string;
    /** Entitlement keys from billing, as a customer should read them. */
    features: Record<string, string>;
  };
  contact: {
    title: string;
    lead: string;
    email: string;
    phone?: string;
    area: string;
  };
  footer: { tagline: string };
};

export type ProductContent = Record<MarketingLocale, ProductCopy>;
