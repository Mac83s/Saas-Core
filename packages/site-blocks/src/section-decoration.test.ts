import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import legacyHero from "@saas-core/contracts/site-blocks/fixtures/core.hero.v1.json";
import {
  coreSiteBlockManifest,
  coreSectionTemplates,
  createSiteBlockRegistry,
  InvalidBlockDataError,
  renderDraftPreview,
  renderPublishedPage,
  replaceSectionLayout,
  sectionDecorationPresets,
  sectionTemplateBlock,
  type DesignTokensV1,
  type SiteBlock,
  type SectionDecorationV1,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const decoration: SectionDecorationV1 = {
  schemaVersion: 1,
  ornament: "rings",
  background: "gradient",
  motion: "drift",
};
const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};

describe("shared section decoration contract", () => {
  it("accepts each preset on every catalog template without altering content", () => {
    const types = new Set<string>();
    for (const template of coreSectionTemplates()) {
      for (const locale of ["pl", "en"] as const) {
        const block = sectionTemplateBlock(template, locale, registry);
        const before = structuredClone(block);
        for (const preset of sectionDecorationPresets) {
          registry.validate({ ...block, decoration: preset.decoration });
          expect(preset.labels[locale].description.length).toBeGreaterThan(10);
        }
        expect(block).toEqual(before);
        types.add(block.block_type);
      }
    }
    // These blocks have no section-layout recipe (or not in this shape), but
    // their envelope must support the same decoration controls.
    const remaining: SiteBlock[] = [
      {
        block_type: "core.rich_text",
        schema_version: 1,
        data: { text: "Useful information" },
      },
      {
        block_type: "core.rich_text",
        schema_version: 2,
        data: {
          content: [
            { type: "heading", level: 2, anchor: "plan", text: "Plan" },
            { type: "paragraph", content: [{ text: "Details", bold: true }] },
          ],
        },
      },
      {
        block_type: "core.quote",
        schema_version: 1,
        data: { quote: "Measure twice.", author: "Sample author" },
      },
      {
        block_type: "core.product",
        schema_version: 1,
        data: {
          title: "Sample product",
          specs: [{ label: "Mass", value: "1 kg" }],
        },
      },
      {
        block_type: "core.testimonials",
        schema_version: 1,
        data: { items: [{ quote: "Helpful", author: "Sample author" }] },
      },
      {
        block_type: "core.pricing",
        schema_version: 1,
        data: { items: [{ name: "Service", price: "On request" }] },
      },
      {
        block_type: "core.booking",
        schema_version: 1,
        data: {
          title: "Book a visit",
          action: { label: "Book", href: "/booking/" },
        },
      },
      {
        block_type: "core.footer",
        schema_version: 1,
        data: { text: "Sample company" },
      },
      { block_type: "core.entry_list", schema_version: 1, data: { items: [] } },
    ];
    for (const block of remaining) {
      for (const preset of sectionDecorationPresets) {
        const html = renderToStaticMarkup(
          registry.render(
            { ...block, decoration: preset.decoration },
            "sample",
          ),
        );
        expect(html).toContain('data-section-decoration="1"');
        expect(html).toContain(`data-block-type="${block.block_type}"`);
      }
      types.add(block.block_type);
    }
    expect(types).toEqual(new Set(registry.definitions.keys()));
    expect(
      new Set(sectionDecorationPresets.map((preset) => preset.id)).size,
    ).toBe(8);
  });

  it.each([
    { schemaVersion: 2 },
    { schemaVersion: 1, background: "url(https://example.com/image)" },
    { schemaVersion: 1, motion: "custom-script" },
    { schemaVersion: 1, css: "position:fixed" },
    { schemaVersion: 1, svg: "<svg onload='alert(1)'/>" },
  ])(
    "rejects untrusted settings and identifies the decoration error: %j",
    (invalid) => {
      try {
        registry.validate({
          ...legacyHero,
          decoration: invalid as unknown as SectionDecorationV1,
        });
        expect.fail(
          "The controlled decoration contract must reject this value",
        );
      } catch (error) {
        expect(error).toBeInstanceOf(InvalidBlockDataError);
        expect(
          (error as InvalidBlockDataError).issues.every(
            (issue) => issue.scope === "decoration",
          ),
        ).toBe(true);
      }
    },
  );

  it("preserves independent settings through content migration and layout replacement", () => {
    const original = {
      ...structuredClone(legacyHero),
      decoration: structuredClone(decoration),
    };
    const before = structuredClone(original);
    const migrated = registry.migrate(original);
    const template = coreSectionTemplates().find(
      (item) =>
        item.blockType === "core.hero" && item.layout !== migrated.data.layout,
    )!;
    const replaced = replaceSectionLayout(migrated, template, registry);
    expect(replaced.decoration).toEqual(decoration);
    expect(replaced.decoration).not.toBe(original.decoration);
    expect(replaced.data.title).toBe(legacyHero.data.heading);
    expect(original).toEqual(before);
  });

  it("keeps published legacy markup unchanged when decoration is absent or empty", () => {
    const plain = renderToStaticMarkup(registry.render(legacyHero, "block"));
    expect(
      renderToStaticMarkup(
        registry.render(
          { ...legacyHero, decoration: { schemaVersion: 1 } },
          "block",
        ),
      ),
    ).toBe(plain);
    expect(registry.migrate(legacyHero)).not.toHaveProperty("decoration");
  });

  it("enables localized motion only on the public page, with static draft and inline previews", () => {
    const blocks = [{ ...legacyHero, decoration }];
    const draft = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft",
          blocks,
          designTokens: tokens,
        },
        registry,
      ),
    );
    expect(draft).toContain("site-decoration--motion-none");
    expect(draft).not.toContain('type="checkbox"');
    const published = renderToStaticMarkup(
      renderPublishedPage(
        {
          kind: "publication",
          publicationId: "published",
          snapshotHash: "a".repeat(64),
          locale: "en",
          blocks,
          designTokens: tokens,
        },
        registry,
      ),
    );
    expect(published).toContain("site-decoration--motion-drift");
    expect(published).toContain("Pause decorative animation");
    const inline = renderToStaticMarkup(
      registry.render(
        blocks[0]!,
        "inline",
        { text: (_path, value) => value },
        undefined,
        undefined,
        { preview: false },
      ),
    );
    expect(inline).toContain("site-decoration--motion-none");
    expect(inline).not.toContain('type="checkbox"');
  });
});
