import { createElement as h } from "react";

import { siteUiTexts } from "./site-ui-texts";
import type { BlockComponentProps, DocumentV1Data } from "./types";

/** „1 października 2026”: a calendar day said in the page's language. */
export function documentDay(day: string, locale: string): string {
  const [year = 1970, month = 1, date = 1] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, date)));
}

/**
 * A company's document on its own site (ADR-072, slice 5f part 2): the text
 * of the version in force, in the page's language, as the page's heading and
 * body. The server builds the block for the document's own page; it is in no
 * library and no draft carries it.
 *
 * A document is written per language. Where the version has no text in the
 * page's language the block shows none: it says so — for the booking terms
 * in the words of the booking form, which is closed in that language
 * (ADR-073) — and links the languages that have the text.
 */
export function DocumentBlock({ data, options }: BlockComponentProps) {
  const block = data as DocumentV1Data;
  const locale = options?.locale ?? "pl";
  const texts = siteUiTexts(locale).document;
  const section = {
    className: "site-block site-block--document",
    "data-block-type": "core.document",
  };
  const head = h(
    "header",
    { className: "site-document__head" },
    h("h1", null, block.title),
    h(
      "p",
      { className: "site-document__version" },
      texts.version(block.version, documentDay(block.effective_from, locale)),
    ),
  );
  if (block.text === undefined) {
    const elsewhere = block.elsewhere ?? [];
    return h(
      "section",
      section,
      head,
      h(
        "div",
        { className: "site-document__missing", role: "note" },
        h(
          "p",
          null,
          block.kind === "booking_terms"
            ? texts.missingBookingTerms
            : texts.missing,
        ),
        elsewhere.length ? h("p", null, texts.readIn) : null,
        elsewhere.length
          ? h(
              "ul",
              { className: "site-document__languages" },
              elsewhere.map((item) =>
                h(
                  "li",
                  { key: item.locale },
                  h(
                    "a",
                    {
                      href: item.href,
                      hrefLang: item.locale,
                      lang: item.locale,
                    },
                    item.name,
                  ),
                ),
              ),
            )
          : null,
      ),
    );
  }
  return h(
    "section",
    section,
    head,
    h(
      "div",
      { className: "site-prose site-document__text" },
      // Paragraphs stand apart by an empty line; a single line break stays
      // a line break (the stylesheet keeps it).
      block.text
        .split(/\n{2,}/)
        .filter((paragraph) => paragraph.trim())
        .map((paragraph, index) => h("p", { key: index }, paragraph)),
    ),
  );
}
