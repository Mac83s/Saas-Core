import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { coreSiteBlockManifest } from "./core-manifest";
import { createSiteBlockRegistry } from "./registry";
import { renderPublishedPage } from "./renderer";
import { renderArticleByline, renderLanguageSwitcher } from "./site-chrome";
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

describe("article byline", () => {
  const article = {
    authorName: "Anna Kowalska",
    // Half past midnight on 1 October in Warsaw.
    publishedAt: "2026-09-30T22:30:00+00:00",
    updatedAt: "2026-09-30T23:10:00+00:00",
    timeZone: "Europe/Warsaw",
  };

  it("names the author and the day in the page's language and the company's zone", () => {
    expect(
      renderToStaticMarkup(
        renderArticleByline(article, "pl", siteUiTexts("pl").updated),
      ),
    ).toBe(
      '<p class="site-article-byline"><span>Anna Kowalska</span>' +
        '<time dateTime="2026-09-30T22:30:00.000Z">1 października 2026</time></p>',
    );
  });

  it("adds the day the text changed once it is a later one", () => {
    const html = renderToStaticMarkup(
      renderArticleByline(
        { ...article, updatedAt: "2026-10-04T08:00:00+00:00" },
        "de",
        siteUiTexts("de").updated,
      ),
    );

    expect(html).toContain(">1. Oktober 2026</time>");
    expect(html).toContain(
      '<span>Aktualisiert <time dateTime="2026-10-04T08:00:00.000Z">4. Oktober 2026</time></span>',
    );
  });

  it("is not there on a page, nor with nothing to say", () => {
    expect(renderArticleByline(null, "pl", "Zaktualizowano")).toBeNull();
    expect(
      renderArticleByline({ authorName: "", publishedAt: null }, "pl", "x"),
    ).toBeNull();
  });

  it("opens the article, before its first section", () => {
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
          article: { ...article, timeZone: "No/Such_Zone" },
        },
        createSiteBlockRegistry([coreSiteBlockManifest]),
      ),
    );

    // A zone the runtime does not know counts the day in UTC.
    expect(html).toContain(
      '<main><p class="site-article-byline"><span>Anna Kowalska</span>' +
        '<time dateTime="2026-09-30T22:30:00.000Z">September 30, 2026</time></p><section',
    );
  });
});
