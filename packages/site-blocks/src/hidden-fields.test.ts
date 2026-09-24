import { describe, expect, it } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  hiddenFields,
  offeredSectionTemplates,
  sectionTemplateBlock,
  defineSiteBlockManifest,
  type SiteBlock,
} from "./index";
import { createElement } from "react";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const names = (block: SiteBlock) =>
  hiddenFields(block, registry).map(({ field, parent }) =>
    [parent?.labelKey, field.labelKey].filter(Boolean).join("."),
  );
const asset = "00000000-0000-4000-8000-000000000001";

describe("hidden fields", () => {
  it("a template's own layout shows everything its seed fills in", () => {
    const report: string[] = [];
    for (const template of offeredSectionTemplates())
      for (const locale of ["pl", "en"] as const) {
        const hidden = names(sectionTemplateBlock(template, locale, registry));
        if (hidden.length)
          report.push(
            `${template.id}@${template.version} ${locale}: ${hidden}`,
          );
      }
    expect(report).toEqual([]);
  });

  it("names what a layout switch leaves out, and nothing no layout shows", () => {
    // Today's layouts rearrange rather than drop fields; a two-layout block
    // pins the rule for the ones that will not.
    const notes = createSiteBlockRegistry([
      coreSiteBlockManifest,
      defineSiteBlockManifest({
        moduleId: "vertical.example",
        namespace: "example",
        blocks: [
          {
            type: "example.notes",
            latestVersion: 1,
            schemas: [
              {
                version: 1,
                schema: {
                  type: "object",
                  additionalProperties: false,
                  required: ["layout", "title"],
                  properties: {
                    layout: { enum: ["full", "short"] },
                    title: { type: "string" },
                    note: { type: "string" },
                    footnote: { type: "string" },
                    image: {
                      type: "object",
                      properties: {
                        asset_id: { type: "string" },
                        alt: { type: "string" },
                      },
                    },
                  },
                },
              },
            ],
            migrators: {},
            component: ({ data, editor, imageRenderer }) => {
              const text = editor?.text ?? ((_, value: string) => value);
              const image = data.image as { asset_id: string; alt: string };
              return createElement(
                "section",
                null,
                text(["title"], String(data.title)),
                data.layout === "full" && data.note
                  ? text(["note"], String(data.note))
                  : null,
                data.layout === "full" && image && imageRenderer
                  ? imageRenderer(image)
                  : null,
              );
            },
            catalog: {
              category: "about",
              labelKey: "notes",
              fields: [
                { path: ["title"], kind: "text", labelKey: "heading" },
                { path: ["note"], kind: "textarea", labelKey: "note" },
                { path: ["footnote"], kind: "text", labelKey: "footnote" },
                {
                  path: ["image", "asset_id"],
                  kind: "media",
                  labelKey: "imageAsset",
                },
              ],
            },
          },
        ],
      }),
    ]);
    const block = (layout: string): SiteBlock => ({
      block_type: "example.notes",
      schema_version: 1,
      data: {
        layout,
        title: "Tytuł",
        note: "Uwaga",
        footnote: "Nigdzie niepokazywany przypis",
        image: { asset_id: asset, alt: "Zdjęcie" },
      },
    });
    const keys = (layout: string) =>
      hiddenFields(block(layout), notes).map(({ field }) => field.labelKey);
    expect(keys("full")).toEqual([]);
    expect(keys("short")).toEqual(["note", "imageAsset"]);
  });

  it("stays quiet on a value that does not render", () => {
    expect(
      hiddenFields(
        {
          block_type: "core.rich_text",
          schema_version: 3,
          data: { layout: 7 },
        },
        registry,
      ),
    ).toEqual([]);
  });
});
