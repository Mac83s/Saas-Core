import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { decorateSection } from "./section-decoration-renderer";
import type { SectionDecorationV1 } from "./types";

const content = h(
  "section",
  { className: "site-block" },
  h("h2", null, "Original heading"),
  h(
    "a",
    { href: "/contact", className: "site-section__action" },
    "Contact our team",
  ),
);

describe("section decoration renderer", () => {
  it("keeps undecorated content unchanged even when nonvisual options are supplied", () => {
    for (const decoration of [
      undefined,
      { schemaVersion: 1 },
      {
        schemaVersion: 1,
        background: "none",
        frame: "none",
        ornament: "none",
        motion: "drift",
        placement: "both",
        intensity: "soft",
      },
    ] as const)
      expect(
        decorateSection(content, decoration, { preview: false }, "unchanged"),
      ).toBe(content);
  });

  it.each(["orbs", "rings", "wave", "botanical", "sparkles"] as const)(
    "keeps %s artwork hidden from assistive technology without hiding or duplicating content",
    (ornament) => {
      const decoration: SectionDecorationV1 = {
        schemaVersion: 1,
        ornament,
        placement: "both",
        background: "gradient",
        frame: "outline",
      };
      const before = structuredClone(decoration);
      const html = renderToStaticMarkup(decorateSection(content, decoration));
      expect(html.match(/Original heading/g)).toHaveLength(1);
      expect(html.match(/href="\/contact"/g)).toHaveLength(1);
      expect(html).toContain('<div class="site-decoration__content"><section');
      expect(html.match(/<svg /g)).toHaveLength(2);
      expect(html.match(/focusable="false"/g)).toHaveLength(2);
      expect(html).not.toMatch(/<svg (?![^>]*aria-hidden="true")/);
      expect(html).not.toMatch(
        /<foreignObject|<image|<script|\b(?:id|xlink:href|style)=/,
      );
      expect(html).not.toContain('type="checkbox"');
      expect(decoration).toEqual(before);
    },
  );

  it("keeps all previews static, including callers that omit the preview option", () => {
    for (const motion of ["drift", "breathe"] as const)
      for (const options of [
        undefined,
        {},
        { locale: "en" as const },
        { preview: true },
      ]) {
        const html = renderToStaticMarkup(
          decorateSection(
            content,
            { schemaVersion: 1, ornament: "orbs", motion },
            options,
          ),
        );
        expect(html).not.toContain('type="checkbox"');
        expect(html).not.toContain(`site-decoration--motion-${motion}`);
        expect(html).toContain("site-decoration--motion-none");
      }
  });

  it.each([
    ["pl", "Wstrzymaj animację dekoracji"],
    ["en", "Pause decorative animation"],
  ] as const)(
    "offers a native, localized pause checkbox in the %s public renderer",
    (locale, label) => {
      for (const motion of ["drift", "breathe"] as const) {
        const html = renderToStaticMarkup(
          decorateSection(
            content,
            { schemaVersion: 1, ornament: "rings", motion },
            { preview: false, locale },
          ),
        );
        expect(html).toContain(
          `type="checkbox" class="site-decoration__pause-input" aria-label="${label}"`,
        );
        expect(html.match(/type="checkbox"/g)).toHaveLength(1);
        expect(html).not.toMatch(/\bid=|\bchecked=|\bonchange=|<script/);
        expect(html).toContain("site-decoration--has-control");
        expect(html).toContain(`site-decoration--motion-${motion}`);
      }
    },
  );

  it("does not expose inactive controls for static ornaments or backgrounds without ornaments", () => {
    for (const decoration of [
      { schemaVersion: 1, ornament: "wave", motion: "none" },
      { schemaVersion: 1, background: "dots", motion: "drift" },
      { schemaVersion: 1, frame: "accent", motion: "breathe" },
    ] as const) {
      const html = renderToStaticMarkup(
        decorateSection(content, decoration, { preview: false }),
      );
      expect(html).not.toContain("site-decoration--has-control");
      expect(html).not.toContain('type="checkbox"');
      expect(html).toContain("site-decoration--motion-none");
    }
  });
});
