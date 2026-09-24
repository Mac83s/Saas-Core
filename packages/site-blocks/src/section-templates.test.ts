import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020.js";
import catalog from "@saas-core/contracts/site-blocks/section-templates.v7.json";
import v6Catalog from "@saas-core/contracts/site-blocks/section-templates.v6.json";
import previousCatalog from "@saas-core/contracts/site-blocks/section-templates.v5.json";
import v4Catalog from "@saas-core/contracts/site-blocks/section-templates.v4.json";
import olderCatalog from "@saas-core/contracts/site-blocks/section-templates.v3.json";
import schema from "@saas-core/contracts/site-blocks/section-templates.v7.schema.json";
import sampleMedia from "@saas-core/contracts/page-templates/sample-media.v1.json";
import {
  availableSectionTemplates,
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  offeredSectionTemplates,
  replaceSectionLayout,
  sectionTemplateBlock,
  type JsonObject,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const context = { entitlements: ["sites.enabled"], modules: ["shared.sites"] };

describe("section template contract", () => {
  it("keeps all historical recipes unchanged when extending the catalogue", () => {
    for (const previous of [
      ...olderCatalog.templates,
      ...v4Catalog.templates,
      ...previousCatalog.templates,
      ...v6Catalog.templates,
    ])
      expect(
        coreSectionTemplates().find(
          (item) =>
            item.id === previous.id && item.version === previous.version,
        ),
      ).toEqual(previous);
  });

  it("appends exactly the sixteen v6 conversion sections to the 104 v5 recipes", () => {
    const v6 = v6Catalog.templates as unknown as typeof catalog.templates;
    expect(v6).toHaveLength(120);
    expect(v6.slice(0, 104)).toEqual(previousCatalog.templates);
    const counts = new Map<string, [number, number]>();
    for (const template of v6) {
      const key = `${template.blockType.replace("core.", "")}@${template.schemaVersion}`;
      const [defaults, industry] = counts.get(key) ?? [0, 0];
      counts.set(
        key,
        template.kind === "default"
          ? [defaults + 1, industry]
          : [defaults, industry + 1],
      );
    }
    expect(Object.fromEntries(counts)).toEqual({
      "hero@5": [20, 6],
      "feature_list@3": [20, 6],
      "feature_list@4": [2, 0],
      "faq@3": [20, 0],
      "contact@2": [6, 0],
      "link_list@1": [6, 0],
      "contact_form@1": [4, 0],
      "separator@1": [8, 0],
      "rich_text@2": [4, 0],
      "rich_text@3": [16, 0],
      "quote@1": [1, 0],
      "product@1": [1, 0],
    });
    const layouts = [
      "lead_statement",
      "two_parts",
      "side_photo",
      "panorama",
      "illustrated",
      "margin_quote",
      "summary_box",
      "expert_note",
      "alternating_chapters",
      "timeline",
      "numbered_sections",
      "manifesto",
      "problem_solution",
      "howto",
      "resources",
      "essay_cta",
    ];
    const added = v6.slice(104);
    expect(added.map((template) => template.id).sort()).toEqual(
      layouts.map((layout) => `core.rich_text_${layout}`).sort(),
    );
    for (const template of added) {
      const layout = template.id.replace("core.rich_text_", "");
      expect(template).toMatchObject({
        blockType: "core.rich_text",
        schemaVersion: 3,
        kind: "default",
        industries: [],
        version: 1,
        layout,
      });
      expect(template.seed.pl.layout).toBe(layout);
      expect(template.seed.en.layout).toBe(layout);
      // Required for every recipe added from v6 on.
      expect(template.conversion).toEqual({
        stage: expect.stringMatching(
          /^(attention|interest|proof|objection|action)$/,
        ),
        primaryAction: expect.any(Boolean),
      });
    }
  });

  it("v7 appends version 2 of the eight phase-2 layouts: conversion-ready, no invented proof", () => {
    expect(coreSectionTemplates()).toHaveLength(128);
    expect(coreSectionTemplates().slice(0, 120)).toEqual(v6Catalog.templates);
    const phaseTwo = [
      "core.rich_text_column",
      "core.rich_text_split_intro",
      "core.rich_text_facts_panel",
      "core.rich_text_chapters",
      "core.feature_list_steps_notes",
      "core.feature_list_benefits_commentary",
      "core.quote_portrait",
      "core.product_showcase",
    ];
    const added = coreSectionTemplates().slice(120);
    expect(added.map((template) => template.id)).toEqual(phaseTwo);
    for (const template of added) {
      const previous = v6Catalog.templates.find(
        (item) => item.id === template.id,
      )!;
      expect(template.version).toBe(2);
      expect(template.layout).toBe(previous.layout);
      // Each on the newest schema of its block type.
      expect(template.schemaVersion).toBe(
        coreSiteBlockManifest.blocks.find(
          (block) => block.type === template.blockType,
        )!.latestVersion,
      );
      expect(template.conversion).toEqual({
        stage: expect.stringMatching(
          /^(attention|interest|proof|objection|action)$/,
        ),
        primaryAction: expect.any(Boolean),
      });
      // Statements and parameters are the owner's to supply.
      const seed = JSON.stringify(template.seed);
      expect(seed).not.toMatch(/przykładowa wypowiedź|example statement/i);
    }
    const product = added.find((item) => item.id === "core.product_showcase")!;
    for (const locale of ["pl", "en"] as const)
      for (const spec of product.seed[locale].specs as { value: string }[])
        expect(spec.value).toMatch(/^\[(Uzupełnij|Fill in): /);
    expect(product.sampleMedia).toMatchObject({
      id: "electronics",
      path: ["images", 0],
    });
  });

  it("offers the newest version of each template, one per id, in catalogue order", () => {
    const offered = offeredSectionTemplates();
    expect(offered).toHaveLength(120);
    // A revision keeps its predecessor's place in the library.
    expect(offered.map((template) => template.id)).toEqual(
      v6Catalog.templates.map((template) => template.id),
    );
    expect(new Set(offered.map((template) => template.id)).size).toBe(120);
    expect(new Set(offered.map((template) => template.id))).toEqual(
      new Set(v6Catalog.templates.map((template) => template.id)),
    );
    for (const template of offered)
      expect(template.version).toBe(
        Math.max(
          ...coreSectionTemplates()
            .filter((item) => item.id === template.id)
            .map((item) => item.version),
        ),
      );
    // One family of twenty editorial layouts, all on rich_text v3 now.
    const richText = offered.filter(
      (template) =>
        template.blockType === "core.rich_text" && template.kind === "default",
    );
    expect(richText).toHaveLength(20);
    expect(new Set(richText.map((template) => template.layout)).size).toBe(20);
    expect(richText.every((template) => template.schemaVersion === 3)).toBe(
      true,
    );
  });
  it("validates the manifest and every localized seed against the canonical schemas", () => {
    const validate = new Ajv2020({ allErrors: true, strict: true }).compile(
      schema,
    );
    expect(validate(catalog), JSON.stringify(validate.errors)).toBe(true);
    const keys = new Set<string>();
    const industries = new Set(catalog.industries.map((item) => item.id));
    const photos = new Set(sampleMedia.media.map((item) => item.id));
    for (const template of coreSectionTemplates()) {
      const key = `${template.id}@${template.version}`;
      expect(keys.has(key)).toBe(false);
      keys.add(key);
      expect(template.kind === "default").toBe(
        template.industries.length === 0,
      );
      template.industries.forEach((id) =>
        expect(industries.has(id)).toBe(true),
      );
      // v7 replaced the enum of ids with the sample media catalogue.
      if (template.sampleMedia)
        expect(photos.has(template.sampleMedia.id)).toBe(true);
      for (const locale of ["pl", "en"] as const) {
        const block = sectionTemplateBlock(template, locale, registry);
        expect(block.data.layout).toBe(template.layout);
        const html = renderToStaticMarkup(registry.render(block, key));
        expect(html).toContain(`data-block-type="${template.blockType}"`);
        if (template.layout !== "classic")
          expect(html).toContain(`data-section-layout="${template.layout}"`);
      }
    }
  });

  it("keeps universal layouts when filtering an industry, and checks capabilities first", () => {
    const all = availableSectionTemplates(registry, context);
    for (const [type, version] of [
      ["core.hero", 5],
      ["core.feature_list", 3],
      ["core.faq", 3],
    ] as const) {
      const defaults = all.filter(
        (item) =>
          item.blockType === type &&
          item.schemaVersion === version &&
          item.kind === "default",
      );
      expect(defaults).toHaveLength(20);
      expect(new Set(defaults.map((item) => item.layout)).size).toBe(20);
    }
    const medicine = availableSectionTemplates(registry, {
      ...context,
      industry: "medicine",
    });
    expect(medicine.filter((item) => item.kind === "default")).toEqual(
      all.filter((item) => item.kind === "default"),
    );
    expect(medicine.filter((item) => item.kind === "industry")).toHaveLength(4);
    for (const industry of ["medicine", "agriculture", "electronics"]) {
      expect(
        all.filter((item) => item.industries.some((tag) => tag === industry)),
      ).toHaveLength(4);
    }
    expect(
      availableSectionTemplates(registry, { ...context, entitlements: [] }),
    ).toEqual([]);
    expect(
      availableSectionTemplates(registry, { ...context, modules: [] }),
    ).toEqual([]);
  });

  it("changes layout without replacing content, dropping items or mutating the source", () => {
    const template = coreSectionTemplates().find(
      (item) => item.layout === "cards",
    )!;
    const original = {
      block_type: "core.feature_list",
      schema_version: 1,
      data: {
        title: "My offer",
        items: Array.from({ length: 12 }, (_, i) => ({
          title: `Service ${i}`,
          text: "Actual description",
        })),
      },
    };
    const before = structuredClone(original);
    const changed = replaceSectionLayout(original, template, registry);
    expect(changed.schema_version).toBe(4);
    expect(changed.data).toEqual({ ...before.data, layout: "cards" });
    expect(original).toEqual(before);
    expect(() =>
      replaceSectionLayout(
        {
          block_type: "core.hero",
          schema_version: 3,
          data: { title: "Hello" },
        },
        template,
        registry,
      ),
    ).toThrow();
  });

  it("rejects unregistered layouts and leaves old schemas immutable", () => {
    for (const [block_type, schema_version, data] of [
      ["core.hero", 4, { title: "Hello" }],
      ["core.feature_list", 2, { items: [{ title: "Service" }] }],
      ["core.faq", 2, { items: [{ question: "Why?", answer: "Because." }] }],
    ] as const) {
      expect(() =>
        registry.validate({
          block_type,
          schema_version,
          data: { ...data, layout: "custom-script" } as unknown as JsonObject,
        }),
      ).toThrow();
    }
    expect(() =>
      registry.validate({
        block_type: "core.hero",
        schema_version: 3,
        data: { title: "Hello", layout: "split" },
      }),
    ).toThrow();
  });

  it("clones localized seeds and renders all list entries in every layout", () => {
    const template = coreSectionTemplates().find(
      (item) => item.layout === "specification",
    )!;
    const block = sectionTemplateBlock(template, "en", registry);
    block.data.title = "Edited";
    expect(sectionTemplateBlock(template, "en", registry).data.title).not.toBe(
      "Edited",
    );
    for (const variant of coreSectionTemplates().filter(
      (item) => item.blockType === "core.feature_list",
    )) {
      const replaced = replaceSectionLayout(
        {
          block_type: "core.feature_list",
          schema_version: 1,
          data: {
            items: Array.from({ length: 12 }, (_, i) => ({
              title: `Unique item ${i}`,
              text: `Unique description ${i}`,
            })),
          },
        },
        variant,
        registry,
      );
      const html = renderToStaticMarkup(registry.render(replaced, variant.id));
      for (let i = 0; i < 12; i++)
        expect(html).toContain(`Unique description ${i}`);
    }
  });
});

describe("editor adapter", () => {
  it("maps every rendered text to its exact data path for every localized layout", () => {
    for (const template of coreSectionTemplates())
      for (const locale of ["pl", "en"] as const) {
        const block = sectionTemplateBlock(template, locale, registry);
        const before = structuredClone(block);
        const paths: string[] = [];
        renderToStaticMarkup(
          registry.render(block, "editor", {
            text: (path, value) => {
              let original: unknown = block.data;
              for (const part of path)
                original = (original as Record<string, unknown>)[part];
              expect(value).toBe(original);
              paths.push(path.join("."));
              return value;
            },
          }),
        );
        if (template.blockType === "core.separator") {
          expect(paths).toEqual([]);
        } else {
          expect(paths.length).toBeGreaterThan(1);
        }
        expect(new Set(paths).size).toBe(paths.length);
        expect(block).toEqual(before);
        const html = renderToStaticMarkup(registry.render(block, "public"));
        expect(html).not.toContain("data-inline");
        expect(html).not.toContain("<button");
        if (template.layout === "accordion")
          expect(html).not.toContain("open=");
      }
  });
});
