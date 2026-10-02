import { describe, expect, it } from "vitest";

import { business } from "./content/business";
import type { ProductCopy } from "./content";
import { marketingLinks } from "./navigation";

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
    expect(links[1]).toEqual({ href: "/katalog", label: "Katalog firm" });
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
});
