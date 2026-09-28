import { describe, expect, it } from "vitest";

import {
  availablePageTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  deadAnchorLinks,
  pageTemplateBlocks,
  sampleData,
  type JsonObject,
  type SiteBlock,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

describe("editor warnings (F4-P1)", () => {
  it("finds demonstration contact data wherever it is written, and nothing real", () => {
    const blocks: { data: JsonObject }[] = [
      {
        data: {
          email: "kontakt@example.com",
          phone: "+48 000 000 000",
          action: { label: "Zadzwoń", href: "tel:+48000000000" },
          items: [{ title: "Wzór", href: "https://example.com/wzor.pdf" }],
        },
      },
      {
        data: {
          email: "kontakt@firma.pl",
          text: "Pisz na biuro@myexample.com albo example.company.pl.",
          phone: "+48 600 000 000",
        },
      },
    ];
    expect(sampleData(blocks)).toEqual([
      { blockIndex: 0, path: ["email"], text: "kontakt@example.com" },
      { blockIndex: 0, path: ["phone"], text: "+48 000 000 000" },
      { blockIndex: 0, path: ["action", "href"], text: "+48000000000" },
      {
        blockIndex: 0,
        path: ["items", "0", "href"],
        text: "example.com/wzor.pdf",
      },
    ]);
  });

  it("reports an in-page link whose anchor no section or heading carries", () => {
    const blocks: SiteBlock[] = [
      {
        block_type: "core.feature_list",
        schema_version: 5,
        data: {
          items: [{ title: "A" }],
          action: { label: "Zapytaj", href: "#kontakt" },
        },
      },
      {
        block_type: "core.rich_text",
        schema_version: 4,
        data: {
          content: [
            { type: "heading", level: 2, anchor: "etapy", text: "Etapy" },
            {
              type: "paragraph",
              content: [
                { text: "Do etapów", href: "#etapy" },
                { text: " i do cennika", href: "#cennik" },
              ],
            },
          ],
        },
      },
    ];
    expect(deadAnchorLinks(blocks)).toEqual([
      { blockIndex: 0, path: ["action", "href"], href: "#kontakt" },
      {
        blockIndex: 1,
        path: ["content", "1", "content", "1", "href"],
        href: "#cennik",
      },
    ]);
    // The form's section anchor is a target like any other.
    expect(
      deadAnchorLinks([
        ...blocks,
        {
          block_type: "core.contact_form",
          schema_version: 2,
          data: { title: "Napisz" },
          presentation: { schemaVersion: 2, anchor: "kontakt" },
        },
      ]).map((link) => link.href),
    ).toEqual(["#cennik"]);
  });

  it("every offered page recipe lands its in-page links on its own sections", () => {
    for (const recipe of availablePageTemplates(registry, ["sites.enabled"]))
      for (const locale of ["pl", "en"] as const)
        expect(
          deadAnchorLinks(pageTemplateBlocks(recipe, registry, locale)),
          `${recipe.id} ${locale}`,
        ).toEqual([]);
  });
});
