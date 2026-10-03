import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { renderLanguageSwitcher } from "./site-chrome";
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
