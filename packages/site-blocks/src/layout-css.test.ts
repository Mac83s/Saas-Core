import { readdirSync, readFileSync } from "node:fs";

import { expect, it } from "vitest";

import { coreSiteBlockManifest } from "./index";

const styles = new URL("../../ui/src/styles/", import.meta.url);
const css = readdirSync(styles)
  .filter((file) => file.endsWith(".css"))
  .map((file) => readFileSync(new URL(file, styles), "utf8"))
  .join("\n");

/** Layouts drawn by their block's structure and base styles, not by a
 *  `--<layout>` rule. Anything else without a rule is a layout nobody styled
 *  (core.testimonials once shipped with no CSS at all). */
const STRUCTURAL: Record<string, readonly string[]> = {
  // Chapters in `.site-section__parts`.
  "core.rich_text": ["two_parts"],
  // The base picture-beside-list arrangement; the other image layouts
  // override it.
  "core.feature_list": ["image_left"],
  // `<details>` elements are the accordion.
  "core.faq": ["accordion"],
  // Drawn by `__rule`, `__dots` and `__shape`; `space` is the gap alone.
  "core.separator": ["space", "line", "dots", "wave", "curve"],
  // The only product layout, styled as `.site-section--product`.
  "core.product": ["showcase"],
};

it("every layout of the newest block schemas has CSS of its own or is drawn by structure", () => {
  const unstyled: string[] = [];
  for (const block of coreSiteBlockManifest.blocks) {
    const schema = block.schemas.find(
      ({ version }) => version === block.latestVersion,
    )!.schema as { properties?: { layout?: { enum?: unknown[] } } };
    for (const layout of schema.properties?.layout?.enum ?? []) {
      if (typeof layout !== "string") continue;
      const rule = new RegExp(`--${layout}(?![a-z0-9_-])`);
      if (!rule.test(css) && !STRUCTURAL[block.type]?.includes(layout))
        unstyled.push(`${block.type}: ${layout}`);
    }
  }
  expect(unstyled).toEqual([]);
});
