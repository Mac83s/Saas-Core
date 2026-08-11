import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import legacyHero from "@saas-core/contracts/site-blocks/fixtures/core.hero.v1.json";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  defineSiteBlockManifest,
  InvalidBlockDataError,
  InvalidBlockManifestError,
  renderDraftPreview,
  renderPublishedPage,
  UnknownBlockTypeError,
  UnknownBlockVersionError,
  type DesignTokensV1,
  type JsonObject,
  type PublishedPageDocument,
} from "./index";

const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};

describe("site block registry", () => {
  it("migrates the backward compatibility fixture linearly without mutation", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const original = structuredClone(legacyHero);

    const migrated = registry.migrate(legacyHero);

    expect(legacyHero).toEqual(original);
    expect(migrated).toEqual({
      block_type: "core.hero",
      schema_version: 2,
      data: {
        title: "Bezpieczna strona organizacji",
        text: "Treść zachowana ze starszej publikacji.",
        action: { label: "Dowiedz się więcej", href: "/oferta/" },
      },
    });
  });

  it("rejects unknown types, versions and fields outside the schema", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

    expect(() =>
      registry.validate({
        block_type: "evil.script",
        schema_version: 1,
        data: {},
      }),
    ).toThrow(UnknownBlockTypeError);
    expect(() =>
      registry.validate({
        block_type: "core.hero",
        schema_version: 99,
        data: {},
      }),
    ).toThrow(UnknownBlockVersionError);
    expect(() =>
      registry.validate({
        block_type: "core.hero",
        schema_version: 2,
        data: { title: "Hello", dangerouslySetInnerHTML: "<script />" },
      }),
    ).toThrow(InvalidBlockDataError);
  });

  it("accepts trusted module manifests without importing vertical code", () => {
    const verticalManifest = defineSiteBlockManifest({
      moduleId: "vertical.medical",
      namespace: "medical",
      blocks: [
        {
          type: "medical.notice",
          latestVersion: 1,
          schemas: [
            {
              version: 1,
              schema: {
                type: "object",
                additionalProperties: false,
                required: ["text"],
                properties: { text: { type: "string" } },
              },
            },
          ],
          migrators: {},
          component: ({ data }: { data: JsonObject }) => String(data.text),
        },
      ],
    });

    const registry = createSiteBlockRegistry([
      coreSiteBlockManifest,
      verticalManifest,
    ]);
    expect(registry.definitions.has("medical.notice")).toBe(true);
    expect(() =>
      defineSiteBlockManifest({
        ...verticalManifest,
        namespace: "other",
      }),
    ).toThrow(InvalidBlockManifestError);
  });
});

describe("allowlisted renderer", () => {
  it("escapes hostile text and never interprets data as HTML, JS or CSS", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const markup = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft-v1",
          designTokens: tokens,
          blocks: [
            {
              block_type: "core.hero",
              schema_version: 2,
              data: {
                title: '<script>alert("xss")</script>',
                text: '<img src=x onerror="alert(1)">',
              },
            },
          ],
        },
        registry,
      ),
    );

    expect(markup).toContain("&lt;script&gt;");
    expect(markup).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    expect(markup).not.toContain("<script>");
    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("style=");
  });

  it("renders the same publication snapshot deterministically", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const publication: PublishedPageDocument = {
      kind: "publication",
      publicationId: "publication-1",
      snapshotHash: "a".repeat(64),
      designTokens: tokens,
      blocks: [
        {
          block_type: "core.rich_text",
          schema_version: 1,
          data: { text: "Stała treść" },
        },
        legacyHero,
      ],
    };

    const first = renderToStaticMarkup(
      renderPublishedPage(publication, registry),
    );
    const second = renderToStaticMarkup(
      renderPublishedPage(structuredClone(publication), registry),
    );

    expect(first).toMatchSnapshot();
    expect(second).toBe(first);
  });

  it("keeps explicit draft preview separate from public publication input", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    expect(() =>
      renderPublishedPage(
        {
          kind: "draft-preview",
          versionId: "draft-v1",
          blocks: [],
          designTokens: tokens,
        } as unknown as PublishedPageDocument,
        registry,
      ),
    ).toThrow("Renderer publiczny wymaga zweryfikowanej publikacji");
  });
});
