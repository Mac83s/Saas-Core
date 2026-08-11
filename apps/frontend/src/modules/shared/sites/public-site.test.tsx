import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { expect, test } from "vitest";

import type { PublicSitePage } from "@saas-core/api-client";

import { publicSiteMetadata, PublicSiteRenderer } from "./public-site";

const page: PublicSitePage = {
  publication_id: "019ff20d-a000-7000-8000-000000000020",
  snapshot_hash: "a".repeat(64),
  locale: "pl",
  canonical_url: "https://clinic.example.test/oferta",
  hreflang: {
    pl: "https://clinic.example.test/oferta",
    en: "https://clinic.example.test/en/offer",
  },
  x_default: "https://clinic.example.test/oferta",
  title: "Oferta",
  description: "Opis oferty",
  social_title: "Oferta social",
  social_description: "Opis social",
  design_tokens: {
    schemaVersion: 1,
    palette: "neutral",
    typography: "sans",
    radius: "medium",
    spacing: "comfortable",
  },
  blocks: [
    {
      block_type: "core.hero",
      schema_version: 1,
      data: { heading: "Bezpieczna oferta", body: "Opis" },
    },
  ],
};

test("renderuje tylko kontrolowane bloki opublikowanego snapshotu", async () => {
  const rendered = render(<PublicSiteRenderer page={page} />);

  expect(
    screen.getByRole("heading", { name: "Bezpieczna oferta" }),
  ).not.toBeNull();
  expect(
    rendered.container.querySelector("[data-block-type='core.hero']"),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("buduje canonical, hreflang i Open Graph z odpowiedzi API", () => {
  const metadata = publicSiteMetadata(page);

  expect(metadata.alternates?.canonical).toBe(page.canonical_url);
  expect(metadata.alternates?.languages).toEqual({
    ...page.hreflang,
    "x-default": page.x_default,
  });
  expect(metadata.openGraph).toMatchObject({
    title: page.social_title,
    description: page.social_description,
    url: page.canonical_url,
  });
});
