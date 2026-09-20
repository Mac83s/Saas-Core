import type { StaticImageData } from "next/image";

/**
 * The copy of a product's marketing site (ADR-048).
 *
 * Content lives here, per product and per locale, and never inside the page
 * components — so moving it to panel-edited rows later swaps the source, not
 * the pages. Interface strings shared by every product (navigation, buttons)
 * are in `messages/*.json` under `Marketing`.
 */
export type MarketingLocale = "pl" | "en";

export type MarketingDetailPage = {
  /** Same stable URL segment in both locales, so the language switcher keeps its path. */
  slug: string;
  navLabel: string;
  seo: { title: string; description: string };
  eyebrow: string;
  headline: string;
  lead: string;
  sections: { title: string; body: string; points?: string[] }[];
  faq: { question: string; answer: string }[];
  cta: { title: string; body: string };
};

export type ProductCopy = {
  seo: { title: string; description: string };
  hero: {
    eyebrow: string;
    headline: string;
    lead: string;
    highlights: string[];
    /** Optional product-owned image shown behind the home hero. */
    backgroundImage?: string;
  };
  features: {
    title: string;
    lead: string;
    items: {
      title: string;
      body: string;
      href?: string;
      linkLabel?: string;
      image?: StaticImageData;
    }[];
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
  /** Optional product pages in the shared marketing layout. */
  pages?: MarketingDetailPage[];
};

export type ProductContent = Record<MarketingLocale, ProductCopy>;
