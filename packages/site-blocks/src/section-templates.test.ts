import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020.js";
import catalog from "@saas-core/contracts/site-blocks/section-templates.v2.json";
import schema from "@saas-core/contracts/site-blocks/section-templates.v2.schema.json";
import {
  availableSectionTemplates,
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  replaceSectionLayout,
  sectionTemplateBlock,
  type JsonObject,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const context = { entitlements: ["sites.enabled"], modules: ["shared.sites"] };

describe("section template contract", () => {
  it("validates the manifest and every localized seed against the canonical schemas", () => {
    const validate = new Ajv2020({ allErrors: true, strict: true }).compile(
      schema,
    );
    expect(validate(catalog), JSON.stringify(validate.errors)).toBe(true);
    const keys = new Set<string>();
    const industries = new Set(catalog.industries.map((item) => item.id));
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
    for (const type of ["core.hero", "core.feature_list", "core.faq"]) {
      const defaults = all.filter(
        (item) => item.blockType === type && item.kind === "default",
      );
      expect(defaults).toHaveLength(20);
      expect(new Set(defaults.map((item) => item.layout)).size).toBe(20);
    }
    const medicine = availableSectionTemplates(registry, {
      ...context,
      industry: "medicine",
    });
    expect(all.filter((item) => item.kind === "default")).toHaveLength(60);
    expect(medicine.filter((item) => item.kind === "default")).toHaveLength(60);
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
    expect(changed.schema_version).toBe(3);
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
        expect(paths.length).toBeGreaterThan(1);
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
