import { expect, test } from "vitest";

import {
  hasBlankLines,
  isRichTextHref,
  normalizeSpans,
  splitParagraph,
} from "./rich-text-spans";

test("normalizacja łączy sąsiadów, usuwa puste i dzieli za długie przebiegi bez utraty tekstu", () => {
  expect(
    normalizeSpans([
      { text: "a", bold: true },
      { text: "" },
      { text: "b", bold: true },
      { text: "c", href: "javascript:x" },
    ]),
  ).toEqual([{ text: "ab", bold: true }, { text: "c" }]);
  const long = "x".repeat(3999) + "🙂" + "y".repeat(5000);
  const parts = normalizeSpans([{ text: long, italic: true }]);
  expect(parts.map((part) => part.text).join("")).toBe(long);
  expect(parts.every((part) => part.text.length <= 4000 && part.italic)).toBe(
    true,
  );
  expect(parts[0].text).toHaveLength(3999);
});

test("adresy linków: tylko lista kontraktu", () => {
  for (const href of [
    "/cennik",
    "https://example.com",
    "mailto:a@b.pl",
    "tel:+48",
    "#kontakt",
  ])
    expect(isRichTextHref(href)).toBe(true);
  for (const href of [
    "//evil.example",
    "http://example.com",
    "javascript:x",
    "#Kontakt",
    "",
  ])
    expect(isRichTextHref(href)).toBe(false);
});

test("podział akapitu po pustych liniach zachowuje znaczniki i spacje", () => {
  const node = {
    type: "paragraph" as const,
    content: [
      { text: "Pierwszy\nwiersz\n\n  Drugi " },
      { text: "gruby\n \n\nTrzeci", bold: true as const },
    ],
  };
  expect(hasBlankLines("a\n  \nb")).toBe(true);
  expect(hasBlankLines("a\nb")).toBe(false);
  expect(splitParagraph(node)).toEqual([
    { type: "paragraph", content: [{ text: "Pierwszy\nwiersz" }] },
    {
      type: "paragraph",
      content: [{ text: "  Drugi " }, { text: "gruby", bold: true }],
    },
    { type: "paragraph", content: [{ text: "Trzeci", bold: true }] },
  ]);
  expect(
    splitParagraph({ type: "paragraph", content: [{ text: "\n\n" }] }),
  ).toEqual([]);
});
