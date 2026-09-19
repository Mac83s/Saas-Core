// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

/**
 * ADR-031 accepts a theme only at WCAG AA. axe cannot check it (jsdom computes
 * no styles and the rule is off), so the pairs the components actually render
 * are checked here, straight from the token blocks of globals.css.
 */
const css = readFileSync(new URL("./globals.css", import.meta.url), "utf8");

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block in globals.css`);
  const body = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6});/gi)].map((m) => [
      m[1],
      m[2],
    ]),
  );
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** [text, surface]: every text token on the surfaces it is drawn on. */
const PAIRS: [text: string, surface: string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["primary-foreground", "primary"],
  ["primary", "background"],
  ["primary", "card"],
  ["secondary-foreground", "secondary"],
  ["muted-foreground", "muted"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["accent-foreground", "accent"],
  ["destructive", "background"],
  ["destructive", "card"],
  ["destructive-foreground", "destructive"],
  ...["success", "warning", "info"].flatMap((tone): [string, string][] => [
    [`${tone}-foreground`, tone],
    [`${tone}-foreground`, "background"],
  ]),
];

describe.each([
  ["light", ":root"],
  ["dark", '[data-color-scheme="dark"]'],
])("%s theme", (_name, selector) => {
  const theme = tokens(selector);

  it.each(PAIRS)("%s on %s passes AA", (text, surface) => {
    expect(theme[text], `--${text}`).toBeDefined();
    expect(theme[surface], `--${surface}`).toBeDefined();
    expect(contrast(theme[text]!, theme[surface]!)).toBeGreaterThanOrEqual(4.5);
  });
});
