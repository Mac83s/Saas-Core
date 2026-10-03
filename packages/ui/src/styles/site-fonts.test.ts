// @vitest-environment node
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

/**
 * A Russian page reads in the theme's own font (TL14): every bundled family
 * but DM Sans has a Cyrillic face, DM Sans falls back to Inter rather than to
 * the system's font, and each file is the one `sources.json` names. A browser
 * fetches a face only for text in its `unicode-range`, so a Polish page never
 * downloads Cyrillic — which is why the faces are split, not whole families.
 */
const here = new URL("./", import.meta.url);
const fonts = readFileSync(new URL("site-fonts.css", here), "utf8");
const RUSSIAN = 0x0436; // ж

interface Face {
  family: string;
  file: string;
  ranges: [number, number][];
}

const faces: Face[] = [...fonts.matchAll(/@font-face\s*{([^}]*)}/g)].map(
  ([, body]) => ({
    family: /font-family:\s*"([^"]+)"/.exec(body)![1],
    file: /url\(\.\/fonts\/([^)]+)\)/.exec(body)![1],
    ranges: /unicode-range:([^;]+);/
      .exec(body)![1]
      .split(",")
      .map((range) => {
        const [start, end = start] = range.trim().slice(2).split("-");
        return [parseInt(start, 16), parseInt(end, 16)] as [number, number];
      }),
  }),
);

function covers(family: string, code: number): boolean {
  return faces.some(
    (face) =>
      face.family === family &&
      face.ranges.some(([start, end]) => start <= code && code <= end),
  );
}

describe("site fonts", () => {
  it.each(["Inter", "Manrope", "Nunito", "Lora", "Playfair Display"])(
    "%s has a Cyrillic face of its own",
    (family) => {
      expect(covers(family, RUSSIAN)).toBe(true);
    },
  );

  it("DM Sans, published without Cyrillic, falls back to Inter in every stack", () => {
    expect(covers("DM Sans", RUSSIAN)).toBe(false);
    for (const name of [
      "site-fonts.css",
      "site-page-styles.css",
      "site-page-presentation.css",
    ]) {
      const css = readFileSync(new URL(name, here), "utf8");
      const stacks = [...css.matchAll(/"DM Sans",[^;]*;/g)].map((m) => m[0]);
      expect(stacks.length, name).toBeGreaterThan(0);
      for (const stack of stacks) expect(stack, name).toMatch(/^"DM Sans", "Inter",/);
    }
  });

  it("serves only files whose source and hash are on record", () => {
    const sources = JSON.parse(
      readFileSync(new URL("fonts/sources.json", here), "utf8"),
    ) as { files: { file: string; sha256: string }[] };
    const recorded = new Map(sources.files.map((item) => [item.file, item.sha256]));
    const bundled = readdirSync(new URL("fonts/", here)).filter((name) =>
      name.endsWith(".woff2"),
    );

    expect(new Set(faces.map((face) => face.file))).toEqual(new Set(bundled));
    for (const file of bundled) {
      const bytes = readFileSync(new URL(`fonts/${file}`, here));
      expect(createHash("sha256").update(bytes).digest("hex"), file).toBe(
        recorded.get(file),
      );
    }
  });
});
