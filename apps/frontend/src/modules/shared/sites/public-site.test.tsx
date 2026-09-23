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
  breadcrumbs: [{ title: "Oferta", path: "/oferta/" }],
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
  navigation: [
    {
      page_id: "019ff20d-a000-7000-8000-000000000030",
      parent_page_id: null,
      title: "Start",
      path: "/",
    },
    {
      page_id: "019ff20d-a000-7000-8000-000000000031",
      parent_page_id: null,
      title: "Oferta",
      path: "/oferta/",
    },
    {
      page_id: "019ff20d-a000-7000-8000-000000000032",
      parent_page_id: "019ff20d-a000-7000-8000-000000000031",
      title: "Konsultacje",
      path: "/oferta/konsultacje/",
    },
  ],
  pagination: null,
  article: null,
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
  expect(metadata.alternates?.types).toEqual({
    "application/rss+xml": [
      { url: "https://clinic.example.test/rss.xml", title: page.title },
    ],
    "application/atom+xml": [
      { url: "https://clinic.example.test/atom.xml", title: page.title },
    ],
  });
  expect(metadata.openGraph).toMatchObject({
    title: page.social_title,
    description: page.social_description,
    url: page.canonical_url,
  });
});

test("renderuje menu nawigacji z opublikowanego snapshotu", async () => {
  const rendered = render(<PublicSiteRenderer page={page} />);

  // Without a menu, every page a visitor cannot guess the address of is
  // unreachable — the pages exist and nothing links to them.
  const nav = screen.getByRole("navigation", { name: "Menu witryny" });
  expect(nav).not.toBeNull();
  const links = screen.getAllByRole("link");
  expect(links.map((link) => link.textContent)).toEqual([
    "Start",
    "Oferta",
    "Konsultacje",
  ]);
  // A child entry is nested under its parent, not flattened beside it.
  const nested = nav.querySelector("li > ul > li > a");
  expect(nested?.textContent).toBe("Konsultacje");
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("stosuje wygląd tej strony z publikacji, a bez niego wygląd witryny", () => {
  const full = render(
    <PublicSiteRenderer
      page={{
        ...page,
        page_presentation: {
          schemaVersion: 1,
          width: "full",
          headingFont: "lora",
        },
      }}
    />,
  );
  expect(full.container.querySelector(".site-theme")).toHaveClass(
    "site-page--full",
    "site-heading-font--lora",
  );
  full.unmount();
  const plain = render(<PublicSiteRenderer page={page} />);
  expect(plain.container.querySelector(".site-page--full")).toBeNull();
});

test("pomija menu, gdy publikacja go nie zawiera", () => {
  render(<PublicSiteRenderer page={{ ...page, navigation: [] }} />);

  expect(screen.queryByRole("navigation")).toBeNull();
});

test("prowadzi czytelnika do dalszych stron indeksu", async () => {
  const rendered = render(
    <PublicSiteRenderer
      page={{
        ...page,
        pagination: {
          page: 2,
          pages: 5,
          previous_path: "/blog/",
          next_path: "/blog/strona/3/",
          previous_url: "https://clinic.example.test/blog/",
          next_url: "https://clinic.example.test/blog/strona/3/",
        },
      }}
    />,
  );

  // Without these links the archive is reachable only from the sitemap, which
  // is to say only by a crawler.
  const pagination = screen.getByRole("navigation", { name: "Strony" });
  expect(pagination.textContent).toContain("Strona 2 z 5");
  expect(pagination.querySelector("a[rel='prev']")?.getAttribute("href")).toBe(
    "/blog/",
  );
  expect(pagination.querySelector("a[rel='next']")?.getAttribute("href")).toBe(
    "/blog/strona/3/",
  );
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("nie pokazuje stronicowania, gdy strona jest tylko jedna", () => {
  render(
    <PublicSiteRenderer
      page={{
        ...page,
        pagination: {
          page: 1,
          pages: 1,
          previous_path: null,
          next_path: null,
          previous_url: null,
          next_url: null,
        },
      }}
    />,
  );

  expect(screen.queryByRole("navigation", { name: "Strony" })).toBeNull();
});
