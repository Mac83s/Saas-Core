import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { coreSiteBlockManifest } from "./core-manifest";
import { createSiteBlockRegistry } from "./registry";
import { renderPublishedPage } from "./renderer";
import {
  articleShowsItsTitle,
  renderArticleHeader,
  renderLanguageSwitcher,
} from "./site-chrome";
import type { SiteBlock } from "./types";
import { SITE_UI_LOCALES, siteUiTexts } from "./site-ui-texts";

describe("site UI texts", () => {
  it("has the platform's languages and reads English for any other", () => {
    expect(SITE_UI_LOCALES).toEqual(["pl", "en", "de", "es", "ru"]);
    expect(siteUiTexts("de").menu).toBe("Menü");
    expect(siteUiTexts("ru").pagination.position(2, 5)).toBe("Страница 2 из 5");
    expect(siteUiTexts("fr")).toBe(siteUiTexts("en"));
  });

  it("gives every language every text", () => {
    const keys = (value: object): string[] =>
      Object.entries(value).flatMap(([key, item]) =>
        typeof item === "object" && item !== null
          ? keys(item).map((inner) => `${key}.${inner}`)
          : [key],
      );
    const polish = keys(siteUiTexts("pl")).sort();
    for (const locale of SITE_UI_LOCALES) {
      expect(keys(siteUiTexts(locale)).sort()).toEqual(polish);
    }
  });
});

describe("language switch", () => {
  const links = [
    { locale: "pl", name: "Polski", path: "/oferta/", current: true },
    { locale: "de", name: "Deutsch", path: "/de/", current: false },
  ];

  it("is plain links in each language, the current one marked", () => {
    const html = renderToStaticMarkup(renderLanguageSwitcher(links, "Sprache"));

    expect(html).toContain(
      '<nav class="site-language-switch" aria-label="Sprache">',
    );
    expect(html).toContain(
      '<a href="/oferta/" hrefLang="pl" lang="pl" aria-current="true">Polski</a>',
    );
    expect(html).toContain(
      '<a href="/de/" hrefLang="de" lang="de">Deutsch</a>',
    );
  });

  it("is not there with one language", () => {
    expect(renderLanguageSwitcher(links.slice(0, 1), "Język")).toBeNull();
    expect(renderLanguageSwitcher(undefined, "Język")).toBeNull();
  });
});

describe("article header", () => {
  const article = {
    title: "Jak dbać o włosy zimą",
    authorName: "Anna Kowalska",
    // Half past midnight on 1 October in Warsaw.
    publishedAt: "2026-09-30T22:30:00+00:00",
    updatedAt: "2026-09-30T23:10:00+00:00",
    timeZone: "Europe/Warsaw",
  };
  const paragraphs: SiteBlock[] = [
    {
      block_type: "core.rich_text",
      schema_version: 2,
      data: {
        content: [
          { type: "paragraph", content: [{ text: "Mróz wysusza włosy." }] },
        ],
      },
    },
  ];
  const withHeading = (text: string): SiteBlock[] => [
    {
      block_type: "core.rich_text",
      schema_version: 2,
      data: {
        content: [
          { type: "paragraph", content: [{ text: "Wstęp." }] },
          { type: "heading", level: 2, anchor: "tytul", text },
          { type: "heading", level: 2, anchor: "dalej", text: "Dalej" },
        ],
      },
    },
  ];
  const hero: SiteBlock = {
    block_type: "core.hero",
    schema_version: 6,
    data: { title: "Zima" },
  };
  const header = (
    blocks: readonly SiteBlock[],
    locale = "pl",
    facts: Parameters<typeof renderArticleHeader>[0] = article,
  ) =>
    renderToStaticMarkup(
      renderArticleHeader(facts, blocks, locale, siteUiTexts(locale).updated),
    );

  it("opens plain paragraphs with the title, the author and the day in the company's zone", () => {
    expect(header(paragraphs)).toBe(
      '<header class="site-block site-article-header"><h1>Jak dbać o włosy zimą</h1>' +
        '<p class="site-article-byline"><span>Anna Kowalska</span>' +
        '<time dateTime="2026-09-30T22:30:00.000Z">1 października 2026</time></p></header>',
    );
  });

  it("leaves the title to a hero, wherever it stands", () => {
    expect(header([hero, ...paragraphs])).not.toContain("<h1>");
    expect(header([...paragraphs, hero])).not.toContain("<h1>");
    expect(header([hero])).toContain("Anna Kowalska");
  });

  it("leaves the title to the text's first heading when that is the title", () => {
    // Case, spacing and closing punctuation apart.
    expect(header(withHeading("  jak dbać o   włosy ZIMĄ?! "))).not.toContain(
      "<h1>",
    );
    expect(articleShowsItsTitle(withHeading("Dalej"), "Dalej")).toBe(true);
    // Another heading, or the title further down, is not the opening.
    expect(header(withHeading("Pielęgnacja"))).toContain(
      "<h1>Jak dbać o włosy zimą</h1>",
    );
    expect(articleShowsItsTitle(withHeading("Pielęgnacja"), "Dalej")).toBe(
      false,
    );
    // The section's own title is its first heading, before any in the text.
    const titled = (title: string): SiteBlock[] => [
      {
        ...withHeading("Pielęgnacja")[0]!,
        data: { ...withHeading("Pielęgnacja")[0]!.data, title },
      },
    ];
    expect(header(titled("Jak dbać o włosy zimą"))).not.toContain("<h1>");
    expect(articleShowsItsTitle(titled("Porady"), "Pielęgnacja")).toBe(false);
    // Only the first text section is the opening.
    expect(
      articleShowsItsTitle(
        [...paragraphs, ...withHeading(article.title)],
        article.title,
      ),
    ).toBe(false);
  });

  it("adds the day the text changed once it is a later one", () => {
    const html = header(paragraphs, "de", {
      ...article,
      updatedAt: "2026-10-04T08:00:00+00:00",
    });

    expect(html).toContain(">1. Oktober 2026</time>");
    expect(html).toContain(
      '<span>Aktualisiert <time dateTime="2026-10-04T08:00:00.000Z">4. Oktober 2026</time></span>',
    );
  });

  it("is not there on a page, nor with nothing to say", () => {
    expect(renderArticleHeader(null, paragraphs, "pl", "x")).toBeNull();
    expect(
      renderArticleHeader(
        { title: " ", authorName: "", publishedAt: null },
        paragraphs,
        "pl",
        "x",
      ),
    ).toBeNull();
  });

  it("opens the published article, before its first section", () => {
    const html = renderToStaticMarkup(
      renderPublishedPage(
        {
          kind: "publication",
          locale: "en",
          publicationId: "pub-1",
          snapshotHash: "a".repeat(64),
          designTokens: {
            schemaVersion: 1,
            palette: "blue",
            typography: "sans",
            radius: "medium",
            spacing: "comfortable",
          },
          blocks: [
            {
              block_type: "core.rich_text",
              schema_version: 1,
              data: { text: "Body" },
            },
          ],
          article: {
            ...article,
            title: "Winter hair",
            timeZone: "No/Such_Zone",
          },
        },
        createSiteBlockRegistry([coreSiteBlockManifest]),
      ),
    );

    // A zone the runtime does not know counts the day in UTC.
    expect(html).toContain(
      '<main><header class="site-block site-article-header"><h1>Winter hair</h1>' +
        '<p class="site-article-byline"><span>Anna Kowalska</span>' +
        '<time dateTime="2026-09-30T22:30:00.000Z">September 30, 2026</time></p></header><section',
    );
  });
});
