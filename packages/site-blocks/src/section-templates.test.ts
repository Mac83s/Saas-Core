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
  sampleMediaOf,
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
    const added = coreSectionTemplates().slice(120, 128);
    expect(added.map((template) => template.id)).toEqual(phaseTwo);
    for (const template of added) {
      const previous = v6Catalog.templates.find(
        (item) => item.id === template.id,
      )!;
      expect(template.version).toBe(2);
      expect(template.layout).toBe(previous.layout);
      // Each on the newest schema of its block type when v7 was cut. Rich
      // text v4 (a link's optional `rel`, ADR-061), feature_list v5 (F4-P1)
      // quote v2 (F4-P2) and product v3 (F4-P4) came later; these templates reach them through
      // identity migrators.
      expect(template.schemaVersion).toBe(
        (
          {
            "core.rich_text": 3,
            "core.feature_list": 4,
            "core.quote": 1,
            "core.product": 2,
          } as Record<string, number>
        )[template.blockType] ??
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

  it("v7 appends F4-P1: six list layouts on feature_list v5 and four add-ons for a practice and a farm", () => {
    expect(coreSectionTemplates().length).toBeGreaterThanOrEqual(138);
    const added = coreSectionTemplates().slice(128, 138);
    expect(
      added.map((template) => [
        template.id,
        template.layout,
        template.industries.join(),
      ]),
    ).toEqual([
      ["core.feature_list_scope_comparison", "scope_comparison", ""],
      ["core.feature_list_shared_roles", "shared_roles", ""],
      ["core.feature_list_scope_limits", "scope_limits", ""],
      ["core.feature_list_staged_preparation", "staged_preparation", ""],
      ["core.feature_list_instruction_notes", "instruction_notes", ""],
      ["core.feature_list_fit_check", "fit_check", ""],
      [
        "core.feature_list_medicine_visit_preparation",
        "staged_preparation",
        "medicine",
      ],
      [
        "core.feature_list_medicine_visit_types",
        "scope_comparison",
        "medicine",
      ],
      [
        "core.feature_list_agriculture_visit_flow",
        "shared_roles",
        "agriculture",
      ],
      [
        "core.feature_list_agriculture_station_setup",
        "instruction_notes",
        "agriculture",
      ],
    ]);
    for (const template of added) {
      expect(template).toMatchObject({
        version: 1,
        blockType: "core.feature_list",
        schemaVersion: 5,
      });
      expect(template.conversion).toBeDefined();
      for (const locale of ["pl", "en"] as const) {
        const seed = template.seed[locale] as {
          items: { group?: string; note?: string; values?: object }[];
          columns?: unknown[];
          action?: { href: string };
        };
        // The EN seed is the same section in another language.
        const other = template.seed[
          locale === "pl" ? "en" : "pl"
        ] as typeof seed;
        expect(seed.items.map((item) => [!!item.group, !!item.note])).toEqual(
          other.items.map((item) => [!!item.group, !!item.note]),
        );
        expect(seed.columns?.length).toBe(other.columns?.length);
        // A library section may land on a page without a #kontakt section:
        // only page recipes link to anchors (F4-P1).
        if (seed.action) expect(seed.action.href).not.toMatch(/^#/);
        // Facts are the owner's: no price, and the numbers are placeholders.
        expect(JSON.stringify(seed)).not.toMatch(/\d+\s?(zł|PLN|EUR|€)/);
      }
    }
    // A layout with columns or groups gets them in its seed.
    const seed = (id: string) =>
      added.find((template) => template.id === id)!.seed.pl as {
        columns?: unknown[];
        items: { group?: string; note?: string }[];
      };
    expect(seed("core.feature_list_scope_comparison").columns).toHaveLength(3);
    expect(seed("core.feature_list_shared_roles").columns).toHaveLength(2);
    expect(
      seed("core.feature_list_scope_limits").items.filter((item) => item.group),
    ).toHaveLength(2);
    expect(
      seed("core.feature_list_instruction_notes").items.some(
        (item) => item.note,
      ),
    ).toBe(true);
  });

  it("v7 appends F4-P2: five quote layouts on quote v2 — the words, names and sources are the owner's", () => {
    expect(coreSectionTemplates().length).toBeGreaterThanOrEqual(143);
    const added = coreSectionTemplates().slice(138, 143);
    expect(added.map((template) => [template.id, template.layout])).toEqual([
      ["core.quote_typographic", "typographic"],
      ["core.quote_context", "context"],
      ["core.quote_source", "source"],
      ["core.quote_voices", "voices"],
      ["core.quote_with_action", "with_action"],
    ]);
    for (const template of added) {
      expect(template).toMatchObject({
        version: 1,
        blockType: "core.quote",
        schemaVersion: 2,
        kind: "default",
        requirements: { media: "none" },
      });
      expect(template.conversion).toBeDefined();
      for (const locale of ["pl", "en"] as const) {
        const seed = template.seed[locale] as {
          quote: string;
          author?: string;
          role?: string;
          image?: unknown;
          voices?: { quote: string; author?: string; role?: string }[];
          action?: { href: string };
        };
        // No invented statement, speaker or face: every one is a marker.
        const marker = /^\[(Uzupełnij|Fill in): [^\]]+\]$/;
        for (const voice of [seed, ...(seed.voices ?? [])]) {
          expect(voice.quote).toMatch(marker);
          expect(voice.author).toMatch(marker);
          expect(voice.role).toMatch(marker);
        }
        expect(seed.image).toBeUndefined();
        // A library section may land on a page without a #kontakt section.
        if (seed.action) expect(seed.action.href).not.toMatch(/^#/);
      }
    }
    const voices = added.find((template) => template.layout === "voices")!;
    expect((voices.seed.pl as { voices: unknown[] }).voices.length + 1).toBe(3);
    // One primary action, and only where the layout is the next step.
    expect(
      added
        .filter((template) => template.conversion?.primaryAction)
        .map((template) => template.layout),
    ).toEqual(["with_action"]);
  });

  it("v7 appends F4-P3: six gallery layouts — sample photos marked as illustrative, titles are the owner's", () => {
    expect(coreSectionTemplates().length).toBeGreaterThanOrEqual(149);
    const added = coreSectionTemplates().slice(143, 149);
    expect(added.map((template) => [template.id, template.layout])).toEqual([
      ["core.gallery_photo_story", "photo_story"],
      ["core.gallery_captioned_grid", "captioned_grid"],
      ["core.gallery_dominant_details", "dominant_details"],
      ["core.gallery_interleaved", "interleaved"],
      ["core.gallery_project_mosaic", "project_mosaic"],
      ["core.gallery_photo_steps", "photo_steps"],
    ]);
    for (const template of added) {
      expect(template).toMatchObject({
        version: 1,
        blockType: "core.gallery",
        schemaVersion: 1,
        kind: "default",
        requirements: { media: "optional" },
      });
      expect(template.conversion).toBeDefined();
      const samples = sampleMediaOf(template);
      expect(samples.length).toBeGreaterThan(1);
      for (const locale of ["pl", "en"] as const) {
        const seed = template.seed[locale] as {
          items: { title?: string; caption?: string }[];
          action?: { href: string };
        };
        // Each sample photo lands on its own item, and the seed stays
        // valid without them (checked by the manifest test).
        expect(samples.map((sample) => sample.path)).toEqual(
          samples.map((_, index) => ["items", index, "image"]),
        );
        expect(samples.length).toBeLessThanOrEqual(seed.items.length);
        // A photo item says the photo is illustrative, or asks for the
        // owner's words: nothing claims a job the owner has not done.
        for (const item of seed.items.slice(0, samples.length))
          expect(`${item.title} ${item.caption}`).toMatch(
            /\[(Uzupełnij|Fill in): |poglądowe|Illustrative/,
          );
        if (seed.action) expect(seed.action.href).not.toMatch(/^#/);
      }
    }
    expect(
      added
        .filter((template) => template.conversion?.primaryAction)
        .map((template) => template.layout),
    ).toEqual(["project_mosaic"]);
  });

  it("v7 appends F4-P4: seven product layouts on product v3 and two electronics add-ons — no price, no invented parameters", () => {
    expect(coreSectionTemplates().length).toBeGreaterThanOrEqual(158);
    const added = coreSectionTemplates().slice(149, 158);
    expect(
      added.map((template) => [
        template.id,
        template.layout,
        template.industries.join(),
      ]),
    ).toEqual([
      ["core.product_detail", "detail", ""],
      ["core.product_spec_groups", "spec_groups", ""],
      ["core.product_uses", "uses", ""],
      ["core.product_in_the_box", "in_the_box", ""],
      ["core.product_variant_guide", "variant_guide", ""],
      ["core.product_materials", "materials", ""],
      ["core.product_how_to_order", "how_to_order", ""],
      ["core.product_electronics_datasheet", "spec_groups", "electronics"],
      ["core.product_electronics_starter_kit", "in_the_box", "electronics"],
    ]);
    const marker = /^\[(Uzupełnij|Fill in): [^\]]+\]$/;
    for (const template of added) {
      expect(template).toMatchObject({
        version: 1,
        blockType: "core.product",
        schemaVersion: 3,
      });
      expect(template.conversion).toBeDefined();
      for (const locale of ["pl", "en"] as const) {
        const seed = template.seed[locale] as {
          specs?: { value: string }[];
          action?: { href: string };
          documents?: { href: string }[];
        };
        // No price or stock anywhere ("no cart" is said, never offered), and
        // the parameters are the owner's to fill in from the product sheet.
        expect(JSON.stringify(seed)).not.toMatch(
          /\d+\s?(zł|PLN|EUR|€)|w magazynie|in stock/i,
        );
        for (const spec of seed.specs ?? []) expect(spec.value).toMatch(marker);
        // A library section may land on a page without a #kontakt section.
        if (seed.action) expect(seed.action.href).not.toMatch(/^#/);
        for (const document of seed.documents ?? [])
          expect(document.href).toMatch(/^https:\/\/example\.com\//);
      }
    }
    expect(
      added
        .filter((template) => template.conversion?.primaryAction)
        .map((template) => template.id),
    ).toEqual([
      "core.product_variant_guide",
      "core.product_how_to_order",
      "core.product_electronics_starter_kit",
    ]);
  });

  it("v7 appends 5f: five sections of offers booked from–to — a choice and words, never a unit, a price or a day", () => {
    expect(coreSectionTemplates()).toHaveLength(163);
    const added = coreSectionTemplates().slice(158, 163);
    expect(
      added.map((template) => [
        template.id,
        template.blockType,
        template.layout,
      ]),
    ).toEqual([
      ["core.stay_search_widget", "core.stay_search", "classic"],
      ["core.stay_units_cards", "core.stay_units", "cards"],
      ["core.stay_units_rows", "core.stay_units", "rows"],
      ["core.stay_calendar_free_days", "core.stay_calendar", "classic"],
      ["core.stay_map_place", "core.stay_map", "classic"],
    ]);
    for (const template of added) {
      expect(template).toMatchObject({
        version: 1,
        schemaVersion: 1,
        kind: "default",
        // Only where the company's bookings are: the library asks for both.
        requirements: {
          requiredEntitlements: ["sites.enabled", "booking.enabled"],
          requiredModules: ["shared.sites", "shared.booking"],
          media: "none",
        },
        // A page's section: an article is not where a stay is booked.
        targetSurface: ["page"],
      });
      expect(template.conversion).toBeDefined();
      expect(sampleMediaOf(template)).toEqual([]);
      for (const locale of ["pl", "en"] as const) {
        const seed = template.seed[locale] as Record<string, unknown>;
        // Words and a layout only: which offer or unit, what it costs and
        // when it is free are the company's live records.
        expect(Object.keys(seed).sort()).toEqual(
          [
            "title",
            "text",
            ...(template.blockType === "core.stay_map" ? [] : ["action_label"]),
            ...(template.blockType === "core.stay_units" ? ["layout"] : []),
          ].sort(),
        );
        expect(JSON.stringify(seed)).not.toMatch(
          /\d+\s?(zł|PLN|EUR|€)|#[a-z]/i,
        );
      }
    }
    // The widget, both lists and the calendar lead to the booking form; the
    // map does not.
    expect(
      added
        .filter((template) => !template.conversion?.primaryAction)
        .map((template) => template.id),
    ).toEqual(["core.stay_map_place"]);
    // Offered only with the company's bookings in hand.
    const ids = (entitlements: string[], modules: string[]) =>
      availableSectionTemplates(registry, { entitlements, modules })
        .map((template) => template.id)
        .filter((id) => id.startsWith("core.stay_"));
    expect(ids(["sites.enabled"], ["shared.sites"])).toEqual([]);
    expect(
      ids(
        ["sites.enabled", "booking.enabled"],
        ["shared.sites", "shared.booking"],
      ),
    ).toEqual(added.map((template) => template.id));
  });

  it("offers the newest version of each template, one per id, in catalogue order", () => {
    const offered = offeredSectionTemplates();
    expect(offered).toHaveLength(155);
    // A revision keeps its predecessor's place in the library; new ids follow.
    expect(offered.map((template) => template.id)).toEqual([
      ...v6Catalog.templates.map((template) => template.id),
      ...coreSectionTemplates()
        .slice(128)
        .map((template) => template.id),
    ]);
    expect(new Set(offered.map((template) => template.id)).size).toBe(155);
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
      for (const sample of sampleMediaOf(template))
        expect(photos.has(sample.id)).toBe(true);
      for (const locale of ["pl", "en"] as const) {
        const block = sectionTemplateBlock(template, locale, registry);
        // A block without layouts (the stay widget, the calendar, the map)
        // is its one classic section and carries no `layout`.
        expect(block.data.layout ?? "classic").toBe(template.layout);
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
    expect(medicine.filter((item) => item.kind === "industry")).toHaveLength(6);
    for (const [industry, count] of [
      ["medicine", 6],
      ["agriculture", 6],
      ["electronics", 6],
    ] as const) {
      expect(
        all.filter((item) => item.industries.some((tag) => tag === industry)),
      ).toHaveLength(count);
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
    expect(changed.schema_version).toBe(5);
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
