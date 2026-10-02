import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { business } from "./content/business";
import type { ProductCopy } from "./content";
import {
  INLINE_NAV_BREAKPOINTS,
  inlineNavFrom,
  marketingLinks,
} from "./navigation";

const labels = {
  features: "Funkcje",
  catalog: "Katalog firm",
  pricing: "Cennik",
  contact: "Kontakt",
};

describe("marketingLinks", () => {
  it("puts the company catalogue in the menu of a product that has one", () => {
    const links = marketingLinks(business.pl, labels, { catalog: true });

    expect(links.map((link) => link.href)).toEqual([
      "/#features",
      "/katalog",
      "/pricing",
      "/contact",
    ]);
    // A full page load: the catalogue's geolocation policy comes with its own
    // response (Caddy, ADR-064 §7), not with the page the visitor came from.
    expect(links[1]).toEqual({
      href: "/katalog",
      label: "Katalog firm",
      document: true,
    });
    expect(links.filter((link) => link.document)).toHaveLength(1);
  });

  it("leaves the catalogue out of a product without profiles", () => {
    const links = marketingLinks(business.pl, labels, { catalog: false });

    expect(links.map((link) => link.href)).not.toContain("/katalog");
  });

  it("lists a product's own pages before the catalogue", () => {
    const copy: ProductCopy = {
      ...business.pl,
      pages: [
        {
          slug: "dla-gabinetow",
          navLabel: "Dla gabinetów",
          seo: { title: "", description: "" },
          eyebrow: "",
          headline: "",
          lead: "",
          sections: [],
          faq: [],
          cta: { title: "", body: "" },
        },
      ],
    };

    const links = marketingLinks(copy, labels, { catalog: true });

    expect(links.map((link) => link.href)).toEqual([
      "/dla-gabinetow",
      "/katalog",
      "/pricing",
      "/contact",
    ]);
  });

  it("moves a header of six links inline only from xl, where they fit", () => {
    const four = marketingLinks(business.pl, labels, { catalog: true });
    const six = [
      { href: "/a", label: "A" },
      { href: "/b", label: "B" },
      ...four,
    ];

    expect(inlineNavFrom(four)).toBe("lg");
    expect(inlineNavFrom(six)).toBe("xl");
  });

  it("keeps anchors and focus below the taller header until its links go inline", () => {
    // MedPlano at 1100 px: the Menu row makes the header 110 px, so the short
    // 80 px padding there hid focused elements under it (WCAG 2.4.11).
    // Tests run from apps/frontend; the stylesheet lives in the UI package.
    const css = readFileSync(
      path.resolve(process.cwd(), "../../packages/ui/src/styles/globals.css"),
      "utf8",
    );

    for (const [inline, width] of Object.entries(INLINE_NAV_BREAKPOINTS)) {
      expect(css).toMatch(
        new RegExp(
          `@media \\(width >= ${width}\\) \\{\\s*html:has\\(\\[data-marketing-header="${inline}"\\]\\)`,
        ),
      );
    }
  });
});
