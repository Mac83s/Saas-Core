import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedPage,
  type DesignTokensV1,
  type PublishedPageDocument,
} from "./index";

const AI = "01a0d300-0000-7000-8000-000000000001";
const REAL = "01a0d300-0000-7000-8000-000000000002";

const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

function page(
  extra: Partial<PublishedPageDocument> = {},
): PublishedPageDocument {
  return {
    kind: "publication",
    publicationId: "publication-ai",
    snapshotHash: "b".repeat(64),
    designTokens: tokens,
    blocks: [
      {
        block_type: "core.hero",
        schema_version: 3,
        data: {
          title: "Pracownia",
          image: { asset_id: AI, alt: "Jasna pracownia" },
        },
      },
      {
        block_type: "core.rich_text",
        schema_version: 2,
        data: {
          content: [
            {
              type: "figure",
              image: { asset_id: REAL, alt: "Nasz zespół" },
            },
            {
              type: "figure",
              image: { asset_id: AI, alt: "Ilustracja" },
            },
          ],
        },
      },
    ],
    ...extra,
  };
}

const render = (document: PublishedPageDocument) =>
  renderToStaticMarkup(renderPublishedPage(document, registry));

describe("AI badge on a published page", () => {
  it("wraps AI images with the badge and a Polish alt suffix", () => {
    const markup = render(page({ aiMediaIds: [AI] }));

    expect(markup.match(/class="site-ai-media"/g)).toHaveLength(2);
    expect(markup.match(/class="site-ai-badge"/g)).toHaveLength(2);
    expect(markup).toContain('aria-hidden="true">AI</span>');
    expect(markup).toContain(
      'alt="Jasna pracownia — obraz wygenerowany przez AI"',
    );
    // The hero keeps its own eager loading inside the wrapper.
    expect(markup).toMatch(
      /<span class="site-ai-media"><img alt="Jasna pracownia[^"]*" decoding="async" loading="eager" src="\/media\/[^"]+"\/>/,
    );
  });

  it("uses the English suffix on an English page", () => {
    const markup = render(page({ aiMediaIds: [AI], locale: "en" }));

    expect(markup).toContain('alt="Ilustracja — AI-generated image"');
    expect(markup).not.toContain("obraz wygenerowany");
  });

  it("leaves every other image exactly as it was", () => {
    const plain = render(page());
    const marked = render(page({ aiMediaIds: [AI] }));
    const realImage = /<img[^>]*alt="Nasz zespół"[^>]*\/>/;

    expect(marked.match(realImage)?.[0]).toBe(plain.match(realImage)?.[0]);
    expect(plain).not.toContain("site-ai");
    // An empty list is the switch turned off: the page renders as before.
    expect(render(page({ aiMediaIds: [] }))).toBe(plain);
    expect(render(page({ aiMediaIds: [REAL.replace("2", "9")] }))).toBe(plain);
  });
});
