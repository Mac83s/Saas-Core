import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { coreSiteBlockManifest } from "./core-manifest";
import { documentDay } from "./document-block";
import { createSiteBlockRegistry } from "./registry";
import { SITE_UI_LOCALES, siteUiTexts } from "./site-ui-texts";
import type { JsonObject } from "./types";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

function drawn(data: JsonObject, locale = "pl"): string {
  return renderToStaticMarkup(
    registry.render(
      { block_type: "core.document", schema_version: 1, data },
      "document",
      undefined,
      undefined,
      undefined,
      { locale },
    ),
  );
}

const terms = {
  kind: "booking_terms",
  title: "Regulamin rezerwacji",
  version: 3,
  effective_from: "2026-10-01",
};

describe("a company's document on its own site", () => {
  it("draws the approved text under the page's heading, paragraph by paragraph", () => {
    const html = drawn({
      ...terms,
      text: "§1 Rezerwacja\nRezerwujesz na doby.\n\n§2 Płatność <b>z góry</b>",
    });

    expect(html).toContain("<h1>Regulamin rezerwacji</h1>");
    expect(html).toContain("Wersja 3, obowiązuje od 1 października 2026");
    // Two paragraphs; the line break inside the first stays the author's,
    // and the text is text — never markup.
    expect(html.match(/<p>/g)).toHaveLength(2);
    expect(html).toContain("<p>§1 Rezerwacja\nRezerwujesz na doby.</p>");
    expect(html).toContain("§2 Płatność &lt;b&gt;z góry&lt;/b&gt;");
    expect(html).not.toContain('role="note"');
  });

  it("says where the booking terms can be read when the language has no text", () => {
    const html = drawn(
      {
        ...terms,
        title: "Booking terms",
        elsewhere: [
          {
            locale: "de",
            name: "Deutsch",
            href: "/de/documents/booking-terms/",
          },
          { locale: "pl", name: "Polski", href: "/documents/booking-terms/" },
        ],
      },
      "en",
    );

    expect(html).toContain("<h1>Booking terms</h1>");
    expect(html).toContain("Version 3, in force from October 1, 2026");
    // The booking form's own words: no terms in a language, no booking in it.
    expect(html).toContain(siteUiTexts("en").document.missingBookingTerms);
    expect(html).toContain(
      '<a href="/documents/booking-terms/" hrefLang="pl" lang="pl">Polski</a>',
    );
    expect(html).toContain(
      '<a href="/de/documents/booking-terms/" hrefLang="de" lang="de">Deutsch</a>',
    );
    expect(html).not.toContain("site-document__text");
  });

  it("says only that another document has no version, and offers nothing it does not have", () => {
    const html = drawn({
      kind: "privacy_policy",
      title: "Polityka prywatności",
      version: 1,
      effective_from: "2026-10-04",
      elsewhere: [],
    });

    expect(html).toContain(siteUiTexts("pl").document.missing);
    expect(html).not.toContain(siteUiTexts("pl").document.missingBookingTerms);
    expect(html).not.toContain(siteUiTexts("pl").document.readIn);
    expect(html).not.toContain("<ul");
  });

  it("is in no library: only the server builds it", () => {
    expect(registry.definitions.get("core.document")?.catalog).toBeUndefined();
  });

  it("has its words in every language a site speaks", () => {
    for (const locale of SITE_UI_LOCALES) {
      const texts = siteUiTexts(locale).document;
      expect(texts.version(2, "X")).toMatch(/2.*X/);
      for (const sentence of [
        texts.missing,
        texts.missingBookingTerms,
        texts.readIn,
      ])
        expect(sentence.length).toBeGreaterThan(10);
    }
    expect(documentDay("2026-01-31", "de")).toBe("31. Januar 2026");
  });
});
