import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { expect, test } from "vitest";

import type { PublicSitePage } from "@saas-core/api-client";

import {
  publicSiteMetadata,
  publicSitePath,
  PublicSiteRenderer,
} from "./public-site";

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
  ai_media_ids: [],
  noindex: false,
  language_links: [],
  feeds: {
    rss: "https://clinic.example.test/rss.xml",
    atom: "https://clinic.example.test/atom.xml",
  },
  social: {
    site_name: "Klinika",
    locale: "pl_PL",
    alternate_locales: ["en_US"],
    image: null,
  },
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

test("oznacza obrazy AI odznaką i dopiskiem w alt (ADR-059)", async () => {
  const aiId = "019ff20d-a000-7000-8000-000000000040";
  const rendered = render(
    <PublicSiteRenderer
      page={{
        ...page,
        blocks: [
          {
            block_type: "core.hero",
            schema_version: 3,
            data: {
              title: "Pracownia",
              image: { asset_id: aiId, alt: "Jasna pracownia" },
            },
          },
        ],
        ai_media_ids: [aiId],
      }}
    />,
  );

  expect(
    screen.getByRole("img", {
      name: "Jasna pracownia — obraz wygenerowany przez AI",
    }),
  ).not.toBeNull();
  const badge = rendered.container.querySelector(".site-ai-badge");
  expect(badge?.textContent).toBe("AI");
  expect(badge?.getAttribute("aria-hidden")).toBe("true");
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("keeps the slash the visitor typed, except on the root", () => {
  expect(publicSitePath(["oferta"], true)).toBe("/oferta/");
  expect(publicSitePath(["oferta"], false)).toBe("/oferta");
  expect(publicSitePath([], true)).toBe("/");
  expect(publicSitePath(undefined)).toBe("/");
});

test("a page that asks not to be indexed says so in its head", () => {
  expect(publicSiteMetadata(page).robots).toBeUndefined();
  expect(publicSiteMetadata({ ...page, noindex: true }).robots).toEqual({
    index: false,
    follow: true,
  });
});

test("switches language with plain links and names the menu in the page's language", () => {
  render(
    <PublicSiteRenderer
      page={{
        ...page,
        locale: "de",
        language_links: [
          { locale: "pl", name: "Polski", path: "/oferta/", current: false },
          { locale: "de", name: "Deutsch", path: "/de/", current: true },
        ],
      }}
    />,
  );

  const switcher = screen.getByRole("navigation", { name: "Sprache" });
  expect(switcher.querySelector('a[hreflang="pl"]')?.getAttribute("href")).toBe(
    "/oferta/",
  );
  expect(switcher.querySelector('a[aria-current="true"]')?.textContent).toBe(
    "Deutsch",
  );
  expect(screen.getByRole("navigation", { name: "Menü" })).not.toBeNull();
});

test("links its own language's feeds and marks a menu name still in the site's language", () => {
  const english: PublicSitePage = {
    ...page,
    locale: "en",
    feeds: {
      rss: "https://clinic.example.test/en/rss.xml",
      atom: "https://clinic.example.test/en/atom.xml",
    },
    navigation: [
      {
        page_id: "019ff20d-a000-7000-8000-000000000040",
        parent_page_id: null,
        title: "Blog",
        path: "/en/blog/",
        lang: "pl",
      },
    ],
  };

  expect(publicSiteMetadata(english).alternates?.types).toEqual({
    "application/rss+xml": [
      { url: "https://clinic.example.test/en/rss.xml", title: page.title },
    ],
    "application/atom+xml": [
      { url: "https://clinic.example.test/en/atom.xml", title: page.title },
    ],
  });
  render(<PublicSiteRenderer page={english} />);
  const menu = screen.getByRole("navigation", { name: "Menu" });
  expect(menu.querySelector('a[href="/en/blog/"]')?.getAttribute("lang")).toBe(
    "pl",
  );
});

test("a shared link says the page's language, the site and, for an article, who wrote it and when", () => {
  const website = publicSiteMetadata(page);
  expect(website.openGraph).toMatchObject({
    type: "website",
    siteName: "Klinika",
    locale: "pl_PL",
    alternateLocale: ["en_US"],
  });
  expect(website.twitter).toMatchObject({ card: "summary" });

  const article = publicSiteMetadata({
    ...page,
    locale: "en",
    social: {
      site_name: "Klinika",
      locale: "en_US",
      alternate_locales: ["pl_PL"],
      image: {
        url: "https://clinic.example.test/media/019ff20d-a000-7000-8000-000000000050",
        alt: "The waiting room",
      },
    },
    article: {
      author_name: "Anna Nowak",
      published_at: "2026-10-01T08:00:00+00:00",
      updated_at: "2026-10-02T08:00:00+00:00",
      tags: [{ slug: "porady", name: "Tips" }],
    },
  });
  expect(article.openGraph).toMatchObject({
    type: "article",
    locale: "en_US",
    publishedTime: "2026-10-01T08:00:00+00:00",
    modifiedTime: "2026-10-02T08:00:00+00:00",
    authors: ["Anna Nowak"],
    tags: ["Tips"],
    images: [
      {
        url: "https://clinic.example.test/media/019ff20d-a000-7000-8000-000000000050",
        alt: "The waiting room",
      },
    ],
  });
  expect(article.twitter).toMatchObject({ card: "summary_large_image" });
});
