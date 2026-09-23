import { expect, test } from "vitest";

import {
  corePageTemplates,
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  pageTemplateBlocks,
  sectionTemplateBlock,
  type RichTextNode,
  type SiteBlock,
} from "@saas-core/site-blocks";

import { fromEditorDoc, toEditorDoc } from "./rich-text-doc";
import { richTextSchema } from "./rich-text-schema";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

/** Every rich text the product ships: the section catalogue's seeds and the
 *  page recipes (retired ones too), both languages, content and aside. */
function shipped(): [string, RichTextNode[]][] {
  const found: [string, RichTextNode[]][] = [];
  const collect = (label: string, block: SiteBlock) => {
    if (block.block_type !== "core.rich_text") return;
    const data = registry.migrate(block).data as {
      content: RichTextNode[];
      aside?: { content: RichTextNode[] };
    };
    found.push([`${label} content`, data.content]);
    if (data.aside) found.push([`${label} aside`, data.aside.content]);
  };
  for (const template of coreSectionTemplates())
    for (const locale of ["pl", "en"] as const)
      collect(
        `${template.id} ${locale}`,
        sectionTemplateBlock(template, locale, registry),
      );
  for (const recipe of corePageTemplates())
    for (const locale of ["pl", "en"] as const)
      pageTemplateBlocks(recipe, registry, locale).forEach((block, index) =>
        collect(`${recipe.id} #${index} ${locale}`, block),
      );
  return found;
}

const cases = shipped();

test("checks every shipped rich text", () => {
  // 20 catalogue layouts × 2 languages plus the recipes' rich text blocks.
  expect(cases.length).toBeGreaterThan(60);
});

test.each(cases)("%s passes through the editor unchanged", (_, content) => {
  const doc = toEditorDoc(content);
  expect(() => richTextSchema.nodeFromJSON(doc).check()).not.toThrow();
  expect(fromEditorDoc(doc)).toEqual(content);
});

const roundTrip = (content: RichTextNode[]) =>
  fromEditorDoc(toEditorDoc(content));

test("keeps marks, links and the text around them", () => {
  const content: RichTextNode[] = [
    {
      type: "paragraph",
      content: [
        { text: "Zobacz " },
        { text: "cennik", bold: true, href: "/cennik" },
        { text: " albo ", italic: true },
        { text: "napisz", bold: true, italic: true, href: "#kontakt" },
        { text: " — 2 × 3\nnowa linia" },
      ],
    },
  ];
  expect(roundTrip(content)).toEqual(content);
});

test("merges neighbouring runs and splits a run over the contract limit", () => {
  const long = "ą".repeat(4500);
  expect(
    roundTrip([
      { type: "paragraph", content: [{ text: "a" }, { text: "b" }] },
      { type: "paragraph", content: [{ text: long, bold: true }] },
    ]),
  ).toEqual([
    { type: "paragraph", content: [{ text: "ab" }] },
    {
      type: "paragraph",
      content: [
        { text: long.slice(0, 4000), bold: true },
        { text: long.slice(4000), bold: true },
      ],
    },
  ]);
});

test("drops text blocks still empty and keeps cards", () => {
  const doc = {
    type: "doc",
    content: [
      { type: "paragraph" },
      { type: "heading", attrs: { level: 2, anchor: "pusty" } },
      {
        type: "bulletList",
        content: [{ type: "listItem", content: [{ type: "paragraph" }] }],
      },
      { type: "quote", attrs: { author: "Ala" } },
    ],
  };
  expect(() => richTextSchema.nodeFromJSON(doc).check()).not.toThrow();
  expect(fromEditorDoc(doc)).toEqual([
    { type: "quote", content: [], author: "Ala" },
  ]);
  expect(roundTrip([])).toEqual([]);
});

test("gives a new heading an anchor once, unique in the text", () => {
  const heading = (text: string) => ({
    type: "heading",
    attrs: { level: 2 },
    content: [{ type: "text", text }],
  });
  expect(
    fromEditorDoc({ type: "doc", content: [heading("Cena"), heading("Cena")] }),
  ).toEqual([
    { type: "heading", level: 2, anchor: "cena", text: "Cena" },
    { type: "heading", level: 2, anchor: "cena-2", text: "Cena" },
  ]);
  // An existing anchor never follows the text.
  const kept: RichTextNode[] = [
    { type: "heading", level: 3, anchor: "stara", text: "Nowy tytuł" },
  ];
  expect(roundTrip(kept)).toEqual(kept);
});

test("keeps an absent field absent and an empty one empty", () => {
  const content: RichTextNode[] = [
    { type: "quote", content: [{ text: "Cytat" }] },
    {
      type: "quote",
      content: [{ text: "Cytat" }],
      author: "",
      source: "Źródło",
      href: "https://example.com/a",
    },
    { type: "note", content: [{ text: "Uwaga" }] },
    { type: "note", tone: "warning", title: "", content: [{ text: "Uwaga" }] },
    {
      type: "figure",
      image: { asset_id: "00000000-0000-4000-8000-000000000001", alt: "Pole" },
    },
    {
      type: "figure",
      image: { asset_id: "00000000-0000-4000-8000-000000000002", alt: "Łąka" },
      caption: "",
      width: "wide",
    },
  ];
  expect(roundTrip(content)).toEqual(content);
});

test("keeps two list levels and folds a deeper one into the second", () => {
  const two: RichTextNode[] = [
    {
      type: "list",
      style: "ordered",
      items: [
        {
          content: [{ text: "Krok" }],
          children: {
            style: "bullet",
            items: [{ content: [{ text: "a" }] }, { content: [{ text: "b" }] }],
          },
        },
        { content: [{ text: "Koniec", bold: true }] },
      ],
    },
  ];
  expect(roundTrip(two)).toEqual(two);

  const item = (text: string, ...rest: object[]) => ({
    type: "listItem",
    content: [
      { type: "paragraph", content: [{ type: "text", text }] },
      ...rest,
    ],
  });
  const bullets = (...items: object[]) => ({
    type: "bulletList",
    content: items,
  });
  // A pasted third level: no text is lost, it joins the second level.
  expect(
    fromEditorDoc({
      type: "doc",
      content: [
        bullets(item("1", bullets(item("1.1", bullets(item("1.1.1")))))),
      ],
    }),
  ).toEqual([
    {
      type: "list",
      style: "bullet",
      items: [
        {
          content: [{ text: "1" }],
          children: {
            style: "bullet",
            items: [
              { content: [{ text: "1.1" }] },
              { content: [{ text: "1.1.1" }] },
            ],
          },
        },
      ],
    },
  ]);
});

test("mirrors the contract: no marks in headings, one paragraph per item", () => {
  expect(() =>
    richTextSchema
      .nodeFromJSON({
        type: "doc",
        content: [
          {
            type: "heading",
            attrs: { level: 2 },
            content: [{ type: "text", text: "x", marks: [{ type: "bold" }] }],
          },
        ],
      })
      .check(),
  ).toThrow();
  expect(() =>
    richTextSchema
      .nodeFromJSON({
        type: "doc",
        content: [
          {
            type: "bulletList",
            content: [
              {
                type: "listItem",
                content: [
                  { type: "paragraph", content: [{ type: "text", text: "a" }] },
                  { type: "paragraph", content: [{ type: "text", text: "b" }] },
                ],
              },
            ],
          },
        ],
      })
      .check(),
  ).toThrow();
});
