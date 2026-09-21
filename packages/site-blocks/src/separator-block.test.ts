import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import schema from "@saas-core/contracts/site-blocks/core.separator.v1.schema.json";
import { createSiteBlockRegistry } from "./registry";
import { SeparatorBlock, type SeparatorV1Data } from "./separator-block";
import type { JsonObject, SiteBlock } from "./types";

const layouts = [
  "space",
  "line",
  "double",
  "dots",
  "wave",
  "curve",
  "zigzag",
  "accent",
] as const;
const registry = createSiteBlockRegistry([
  {
    namespace: "core",
    moduleId: "shared.sites",
    blocks: [
      {
        type: "core.separator",
        latestVersion: 1,
        schemas: [{ version: 1, schema }],
        migrators: {},
        component: SeparatorBlock,
      },
    ],
  },
]);

function block(data: JsonObject): SiteBlock {
  return { block_type: "core.separator", schema_version: 1, data };
}

describe("decorative separator contract", () => {
  it("renders an empty draft with defaults without mutating the saved data", () => {
    const original = block({});
    const html = renderToStaticMarkup(registry.render(original, "default"));
    expect(html).toContain('data-block-type="core.separator"');
    expect(html).toContain('data-section-layout="line"');
    expect(html).toContain('aria-hidden="true"');
    expect(original.data).toEqual({});
  });

  it.each(layouts)(
    "keeps %s decorative and independent of content editing",
    (layout) => {
      const editText = vi.fn(() => h("button", { type: "button" }, "Edit"));
      for (const size of ["small", "medium", "large"] as const)
        for (const width of ["full", "content", "short"] as const)
          for (const tone of ["muted", "accent"] as const) {
            const data: SeparatorV1Data = { layout, size, width, tone };
            const before = structuredClone(data);
            const html = renderToStaticMarkup(
              registry.render(block(data), `${size}-${width}-${tone}`, {
                text: editText,
              }),
            );
            expect(html).toMatch(/^<div [^>]*aria-hidden="true"/);
            expect(html).not.toMatch(
              /<(?:a|button|input|textarea|select|hr|h[1-6])(?:\s|>)/,
            );
            expect(html).not.toMatch(/\b(?:role|tabindex|style|href|src)=/);
            expect(html).not.toContain("<title");
            expect(data).toEqual(before);
          }
      expect(editText).not.toHaveBeenCalled();
    },
  );

  it("keeps spacing empty and uses distinct fixed SVG shapes without IDs or external references", () => {
    const spacing = renderToStaticMarkup(
      registry.render(block({ layout: "space" }), "space"),
    );
    expect(spacing).toMatch(/^<div [^>]+><\/div>$/);
    const paths = new Set<string>();
    for (const layout of ["wave", "curve", "zigzag"] as const) {
      const html = renderToStaticMarkup(
        registry.render(block({ layout }), layout),
      );
      expect(html).toContain('focusable="false"');
      expect(html).toContain('vector-effect="non-scaling-stroke"');
      expect(html).not.toMatch(
        /\b(?:id|href|xlink:href)=|<foreignObject|<use|<image|<script/,
      );
      paths.add(html.match(/<path d="([^"]+)"/)![1]!);
    }
    expect(paths.size).toBe(3);
  });

  it.each([
    { layout: "custom" },
    { size: 120 },
    { size: "100vh" },
    { width: "calc(100% + 20rem)" },
    { tone: "url(https://outside.example/image.svg)" },
    { layout: null },
    { html: "<script>alert(1)</script>" },
    { svg: "<svg><foreignObject>content</foreignObject></svg>" },
    { path: "M0 0L200 200" },
    { style: { position: "fixed" } },
    { label: "Hidden meaningful text" },
    { href: "https://outside.example" },
  ])("rejects unsupported or executable customization %j", (data) => {
    expect(() =>
      registry.render(block(data as unknown as JsonObject), "invalid"),
    ).toThrow();
  });
});
