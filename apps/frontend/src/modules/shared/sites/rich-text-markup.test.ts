import { expect, test } from "vitest";

import type { RichTextSpan } from "@saas-core/site-blocks";

import {
  hasBlankLines,
  listToText,
  markupToSpans,
  normalizeSpans,
  splitParagraph,
  spansToMarkup,
  textToListItems,
} from "./rich-text-markup";

test.each([
  ["**pogrubienie**", [{ text: "pogrubienie", bold: true }]],
  ["*kursywa*", [{ text: "kursywa", italic: true }]],
  ["***oba***", [{ text: "oba", bold: true, italic: true }]],
  [
    "Zobacz [**cennik** usług](/cennik).",
    [
      { text: "Zobacz " },
      { text: "cennik", bold: true, href: "/cennik" },
      { text: " usług", href: "/cennik" },
      { text: "." },
    ],
  ],
  [
    "**a [b](#sekcja) c**",
    [
      { text: "a ", bold: true },
      { text: "b", bold: true, href: "#sekcja" },
      { text: " c", bold: true },
    ],
  ],
  ["2 \\* 3 \\[x\\] \\(y\\) \\\\", [{ text: "2 * 3 [x] (y) \\" }]],
  ["C:\\temp", [{ text: "C:\\temp" }]],
  ["a * b", [{ text: "a * b" }]],
  ["**nie domknięte", [{ text: "**nie domknięte" }]],
  ["****", [{ text: "****" }]],
  ["[etykieta](javascript:alert(1))", [{ text: "etykieta)" }]],
  ["[x](//evil.example)", [{ text: "x" }]],
  ["[bez adresu] (tekst)", [{ text: "[bez adresu] (tekst)" }]],
  ["[](/pusty)", []],
  ["  dwie  spacje  ", [{ text: "  dwie  spacje  " }]],
  [
    "[wiki](https://pl.wikipedia.org/wiki/A_\\(litera\\))",
    [{ text: "wiki", href: "https://pl.wikipedia.org/wiki/A_(litera)" }],
  ],
])("markupToSpans(%j)", (markup, spans) => {
  expect(markupToSpans(markup)).toEqual(spans);
});

test("zapis w polu jest kanoniczny: dokładnie jedna postać na każdy zestaw przebiegów", () => {
  expect(
    spansToMarkup([
      { text: "a", bold: true },
      { text: "b", bold: true, italic: true },
      { text: "c" },
    ]),
  ).toBe("**a*b***c");
  expect(
    spansToMarkup([
      { text: "a ", bold: true },
      { text: "link", href: "https://example.com/(x)" },
    ]),
  ).toBe("**a [**link**](https://example.com/\\(x\\))**");
  // Invalid addresses never reach the notation; the label survives.
  expect(spansToMarkup([{ text: "x", href: "javascript:alert(1)" }])).toBe("x");
});

/** Deterministic pseudo-random generator: failures reproduce. */
function random(seed: number) {
  return () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
}

const ALPHABET = [
  "a",
  "ż",
  " ",
  "  ",
  "*",
  "**",
  "\\",
  "[",
  "]",
  "(",
  ")",
  "\n",
  "#",
  "1.",
  "🙂",
  "x y",
];
const HREFS = [
  undefined,
  "/o-nas",
  "https://example.com/a(b)",
  "mailto:a@b.pl",
  "tel:+48",
  "#faq",
  "javascript:x",
  "//host",
];

function generateSpans(next: () => number): RichTextSpan[] {
  const pick = <T>(items: readonly T[]) =>
    items[Math.floor(next() * items.length)];
  return Array.from({ length: Math.floor(next() * 7) }, () => {
    const text = Array.from({ length: Math.floor(next() * 5) }, () =>
      pick(ALPHABET),
    ).join("");
    const href = next() < 0.3 ? pick(HREFS) : undefined;
    return {
      text,
      ...(next() < 0.4 ? { bold: true as const } : {}),
      ...(next() < 0.4 ? { italic: true as const } : {}),
      ...(href ? { href } : {}),
    };
  });
}

test("przebiegi → zapis → przebiegi daje postać znormalizowaną, a zapis kanoniczny wraca bez zmian (2000 przypadków)", () => {
  const next = random(20260923);
  for (let run = 0; run < 2000; run += 1) {
    const spans = generateSpans(next);
    const markup = spansToMarkup(spans);
    const parsed = markupToSpans(markup);
    expect(parsed, markup).toEqual(normalizeSpans(spans));
    expect(spansToMarkup(parsed)).toBe(markup);
    for (const span of parsed) expect(span.text).not.toBe("");
  }
});

test("dowolny tekst wpisany ręcznie daje poprawne przebiegi, a ich zapis jest stabilny", () => {
  const next = random(7);
  const pieces = [...ALPHABET, "[a](/b)", "[a](bad)", "***", "](", "\\*"];
  for (let run = 0; run < 1000; run += 1) {
    const typed = Array.from(
      { length: Math.floor(next() * 10) },
      () => pieces[Math.floor(next() * pieces.length)],
    ).join("");
    const spans = markupToSpans(typed);
    expect(spans).toEqual(normalizeSpans(spans));
    const canonical = spansToMarkup(spans);
    expect(markupToSpans(canonical), typed).toEqual(spans);
  }
});

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
  expect(markupToSpans(spansToMarkup(parts))).toEqual(parts);
});

test("lista: wiersz to pozycja, wcięcie to podpozycja ze stylem z numeracji", () => {
  const items = textToListItems(
    [
      "Pierwsza **ważna**",
      "",
      "  1. krok a",
      "\t2. krok b",
      "      głębiej spłaszczone",
      "Druga",
      "  - punkt",
      "  zwykły",
      "   ",
    ].join("\n"),
  );
  expect(items).toEqual([
    {
      content: [{ text: "Pierwsza " }, { text: "ważna", bold: true }],
      children: {
        style: "ordered",
        items: [
          { content: [{ text: "krok a" }] },
          { content: [{ text: "krok b" }] },
          { content: [{ text: "głębiej spłaszczone" }] },
        ],
      },
    },
    {
      content: [{ text: "Druga" }],
      children: {
        style: "bullet",
        items: [
          { content: [{ text: "punkt" }] },
          { content: [{ text: "zwykły" }] },
        ],
      },
    },
  ]);
  expect(textToListItems(listToText(items))).toEqual(items);
  expect(listToText(items)).toBe(
    "Pierwsza **ważna**\n  1. krok a\n  2. krok b\n  3. głębiej spłaszczone\nDruga\n  - punkt\n  - zwykły",
  );
  // Text that looks like a marker survives inside a bullet sub-item.
  const tricky = [
    {
      content: [{ text: "a" }],
      children: {
        style: "bullet" as const,
        items: [
          { content: [{ text: "2020. rok" }] },
          { content: [{ text: "- myślnik" }] },
        ],
      },
    },
  ];
  expect(textToListItems(listToText(tricky))).toEqual(tricky);
  expect(textToListItems("  wcięta pierwsza")).toEqual([
    { content: [{ text: "wcięta pierwsza" }] },
  ]);
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
