import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import legacyHero from "@saas-core/contracts/site-blocks/fixtures/core.hero.v1.json";

import {
  availablePageTemplates,
  coreSiteBlockManifest,
  corePageTemplates,
  createSiteBlockRegistry,
  defineSiteBlockManifest,
  InvalidBlockDataError,
  InvalidBlockManifestError,
  InvalidPageTemplateError,
  pageTemplateBlocks,
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
    // v1 -> v2 -> v3 -> v4 in one pass. The picture v3 added is optional, so a hero
    // published before images existed arrives with its fields untouched.
    expect(migrated).toEqual({
      block_type: "core.hero",
      schema_version: 4,
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
      moduleId: "vertical.example",
      namespace: "example",
      blocks: [
        {
          type: "example.notice",
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
    expect(registry.definitions.has("example.notice")).toBe(true);
    expect(() =>
      defineSiteBlockManifest({
        ...verticalManifest,
        namespace: "other",
      }),
    ).toThrow(InvalidBlockManifestError);
  });

  it("rejects a catalogue field the block schema does not declare", () => {
    const withBadPath = (
      path: readonly string[],
      kind: "text" | "list" = "text",
    ) =>
      defineSiteBlockManifest({
        moduleId: "vertical.example",
        namespace: "example",
        blocks: [
          {
            type: "example.notice",
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
            catalog: {
              category: "about",
              labelKey: "notice",
              fields: [{ path, kind, labelKey: "text" }],
            },
          },
        ],
      });

    // A field bound to a property the contract does not have would render an
    // input whose value the backend always rejects.
    expect(() => withBadPath(["headline"])).toThrow(InvalidBlockManifestError);
    // `text` is a string, so it cannot back a repeatable list.
    expect(() => withBadPath(["text"], "list")).toThrow(
      InvalidBlockManifestError,
    );
    expect(() => withBadPath(["text"])).not.toThrow();
  });

  it("validates the repeatable catalogue blocks against their contracts", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

    expect(() =>
      registry.validate({
        block_type: "core.faq",
        schema_version: 1,
        data: { items: [{ question: "Ile to trwa?", answer: "Godzinę." }] },
      }),
    ).not.toThrow();
    // `items` is required and must hold at least one entry: an empty FAQ would
    // publish a heading with nothing under it.
    expect(() =>
      registry.validate({
        block_type: "core.faq",
        schema_version: 1,
        data: { items: [] },
      }),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate({
        block_type: "core.contact",
        schema_version: 1,
        data: { email: "not-an-address" },
      }),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate({
        block_type: "core.testimonials",
        schema_version: 1,
        data: { items: [{ quote: "Pomogło.", author: "Anna" }] },
      }),
    ).not.toThrow();
    expect(() =>
      registry.validate({
        block_type: "core.pricing",
        schema_version: 1,
        data: { items: [{ name: "Konsultacja", price: "200 zł" }] },
      }),
    ).not.toThrow();
    expect(() =>
      registry.validate({
        block_type: "core.booking",
        schema_version: 1,
        data: {
          title: "Umów termin",
          action: { label: "Rezerwuj", href: "javascript:alert(1)" },
        },
      }),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate({
        block_type: "core.footer",
        schema_version: 1,
        data: { text: "© Firma", links: [{ label: "Regulamin" }] },
      }),
    ).toThrow(InvalidBlockDataError);
  });

  it("covers every ADR-031 catalogue category exactly once", () => {
    const categories = coreSiteBlockManifest.blocks.flatMap((block) =>
      block.catalog === undefined ? [] : [block.catalog.category],
    );

    expect(categories).toHaveLength(9);
    expect(new Set(categories)).toEqual(
      new Set([
        "start",
        "about",
        "offer",
        "trust",
        "pricing",
        "faq",
        "contact",
        "booking",
        "footer",
      ]),
    );
  });
});

describe("page templates", () => {
  it("seeds blocks that pass the live registry and never share state", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const template = corePageTemplates().find(
      ({ id }) => id === "core.specialist_landing",
    );
    if (template === undefined) throw new Error("template missing");

    const first = pageTemplateBlocks(template, registry);
    const second = pageTemplateBlocks(template, registry);
    for (const block of first) registry.validate(block);
    expect(first.map((block) => block.block_type)).toEqual([
      "core.hero",
      "core.feature_list",
      "core.faq",
      "core.contact",
    ]);

    // Applying a template twice must not let the first page's edits leak into
    // the second: the recipe is a shared module-level object.
    (first[0].data as { title: string }).title = "Zmienione";
    expect((second[0].data as { title: string }).title).not.toBe("Zmienione");
  });

  it("hides a template whose blocks or entitlements the deployment lacks", () => {
    const full = createSiteBlockRegistry([coreSiteBlockManifest]);
    expect(
      availablePageTemplates(full, ["sites.enabled"]).map(({ id }) => id),
    ).toEqual([
      "core.profile",
      "core.specialist_landing",
      "core.company",
      "core.service_landing",
    ]);

    // Without the entitlement the recipe declares, nothing is offered.
    expect(availablePageTemplates(full, [])).toEqual([]);

    // A deployment that ships only the hero block cannot offer a recipe that
    // seeds a contact section — better to hide it than to fail on save.
    const heroOnly = createSiteBlockRegistry([
      {
        ...coreSiteBlockManifest,
        blocks: coreSiteBlockManifest.blocks.filter(
          ({ type }) => type === "core.hero",
        ),
      },
    ]);
    expect(availablePageTemplates(heroOnly, ["sites.enabled"])).toEqual([]);
  });

  it("refuses to seed a recipe the registry rejects", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    expect(() =>
      pageTemplateBlocks(
        {
          id: "core.broken",
          version: 1,
          category: "profile",
          labels: {
            pl: { name: "x", description: "x" },
            en: { name: "x", description: "x" },
          },
          blocks: [
            { block_type: "core.hero", schema_version: 2, data: { title: "" } },
          ],
        },
        registry,
      ),
    ).toThrow(InvalidPageTemplateError);
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

  it("renders the four catalogue additions as controlled semantic markup", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const markup = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft-new-categories",
          designTokens: tokens,
          blocks: [
            {
              block_type: "core.testimonials",
              schema_version: 1,
              data: {
                title: "Opinie",
                items: [
                  {
                    quote: "<script>nie wykonuj</script>",
                    author: "Anna",
                    role: "Klientka",
                  },
                ],
              },
            },
            {
              block_type: "core.pricing",
              schema_version: 1,
              data: {
                items: [
                  {
                    name: "Konsultacja",
                    price: "200 zł",
                    description: "60 minut",
                  },
                ],
              },
            },
            {
              block_type: "core.booking",
              schema_version: 1,
              data: {
                title: "Umów termin",
                action: { label: "Rezerwuj", href: "/rezerwacja/" },
              },
            },
            {
              block_type: "core.footer",
              schema_version: 1,
              data: {
                text: "© Firma",
                links: [
                  { label: "Regulamin", href: "/regulamin/" },
                  { label: "Partner", href: "https://example.com/" },
                ],
              },
            },
          ],
        },
        registry,
      ),
    );

    expect(markup).toContain('data-block-type="core.testimonials"');
    expect(markup).toContain("<blockquote>");
    expect(markup).toContain("&lt;script&gt;nie wykonuj&lt;/script&gt;");
    expect(markup).toContain('data-block-type="core.pricing"');
    expect(markup).toContain('data-block-type="core.booking"');
    expect(markup).toContain('href="/rezerwacja/"');
    expect(markup).toContain('data-block-type="core.footer"');
    expect(markup).toContain('href="https://example.com/" rel="noreferrer"');
    expect(markup).not.toContain("<script>");
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

describe("preview landmarks", () => {
  it("keeps `main` for a publication and drops it for an embedded preview", () => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const blocks = [
      {
        block_type: "core.rich_text" as const,
        schema_version: 1,
        data: { text: "Treść" },
      },
    ];

    const published = renderToStaticMarkup(
      renderPublishedPage(
        {
          kind: "publication",
          publicationId: "pub-1",
          snapshotHash: "a".repeat(64),
          designTokens: tokens,
          blocks,
        },
        registry,
      ),
    );
    const preview = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft-v1",
          designTokens: tokens,
          blocks,
        },
        registry,
      ),
    );

    // The published page is the document, so it owns the landmark. A preview is
    // always embedded in one — the panel, the template gallery, a dialog — and
    // a second non-hidden `main` leaves a screen reader unable to say which one
    // is the page.
    expect(published).toContain("<main>");
    expect(preview).not.toContain("<main>");
    expect(preview).toContain('data-block-type="core.rich_text"');
  });
});

it.each(["classic", "centered", "split"])(
  "projects draft images without changing publication markup (%s)",
  (layout) => {
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const block = {
      block_type: "core.hero",
      schema_version: 4,
      data: {
        title: "Clinic",
        layout,
        image: {
          asset_id: "00000000-0000-4000-8000-000000000001",
          alt: "Room",
        },
      },
    };
    const document = {
      kind: "draft-preview" as const,
      versionId: "draft",
      blocks: [block],
      designTokens: tokens,
    };
    const original = JSON.stringify(block);
    const draft = renderToStaticMarkup(
      renderDraftPreview(document, registry, (image) => `private:${image.alt}`),
    );
    expect(draft).toContain("private:Room");
    expect(draft).toContain("<h1>Clinic</h1>");
    expect(draft).not.toContain("/media/");
    const publication = renderToStaticMarkup(
      renderPublishedPage(
        {
          ...document,
          kind: "publication",
          publicationId: "published",
          snapshotHash: "a".repeat(64),
        },
        registry,
      ),
    );
    expect(publication).toContain(`/media/${block.data.image.asset_id}`);
    expect(publication).not.toContain("private:");
    expect(JSON.stringify(block)).toBe(original);
  },
);
