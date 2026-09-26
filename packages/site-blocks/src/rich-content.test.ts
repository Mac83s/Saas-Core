import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import legacyRichText from "@saas-core/contracts/site-blocks/fixtures/core.rich_text.v1.json";
import heroV6Schema from "@saas-core/contracts/site-blocks/core.hero.v6.schema.json";

import {
  applySampleMedia,
  bindTemplateMedia,
  blockAssetIds,
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  ensureUniqueAnchors,
  InvalidBlockDataError,
  InvalidPageTemplateError,
  pagePresentationClassName,
  pageTemplateBlocks,
  renderDraftPreview,
  renderPublishedPage,
  richTextAnchors,
  sectionTemplateBlock,
  templatePreviewAssetId,
  type BlockEditor,
  type DesignTokensV1,
  type JsonObject,
  type PagePresentationV1,
  type PagePresentationV2,
  type PageTemplate,
  type SiteBlock,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};
const photo = "11111111-2222-4333-8444-555555555555";
const other = "66666666-7777-4888-8999-000000000000";

/** Every node type, marks, links, one nested list level and an aside. */
const article: JsonObject = {
  layout: "chapters",
  title: "Poradnik",
  lead: "Krótki wstęp.",
  content: [
    {
      type: "heading",
      level: 2,
      anchor: "przygotowanie",
      text: "Przygotowanie",
    },
    {
      type: "paragraph",
      content: [
        { text: "Zwykły " },
        { text: "gruby", bold: true },
        { text: "pochyły", italic: true },
        {
          text: "link",
          bold: true,
          italic: true,
          href: "https://example.com/",
        },
        { text: "kotwica", href: "#przebieg" },
      ],
    },
    { type: "heading", level: 3, anchor: "narzedzia", text: "Narzędzia" },
    {
      type: "list",
      style: "bullet",
      items: [
        {
          content: [{ text: "Pierwszy" }],
          children: {
            style: "ordered",
            items: [{ content: [{ text: "Podpunkt" }] }],
          },
        },
        { content: [{ text: "Drugi" }] },
      ],
    },
    { type: "heading", level: 2, anchor: "przebieg", text: "Przebieg" },
    {
      type: "quote",
      content: [{ text: "Mierz dwa razy." }],
      author: "Anna Nowak",
      source: "Poradnik stolarza",
      href: "https://example.com/zrodlo",
    },
    {
      type: "note",
      tone: "warning",
      title: "Uwaga",
      content: [{ text: "Wyłącz zasilanie." }],
    },
    {
      type: "figure",
      image: { asset_id: photo, alt: "Warsztat" },
      caption: "Stanowisko pracy",
      width: "wide",
    },
    { type: "heading", level: 4, anchor: "detal", text: "Detal" },
  ],
  aside: {
    title: "Najważniejsze",
    content: [
      { type: "paragraph", content: [{ text: "Fakt pierwszy" }] },
      {
        type: "list",
        style: "ordered",
        items: [{ content: [{ text: "Krok" }] }],
      },
    ],
  },
};
const richText = (data: JsonObject): SiteBlock => ({
  block_type: "core.rich_text",
  schema_version: 2,
  data,
});

function editorPaths(block: SiteBlock): string[] {
  const paths: string[] = [];
  const editor: BlockEditor = {
    text: (path, value) => {
      let original: unknown = registry.migrate(block).data;
      for (const part of path)
        original = (original as Record<string, unknown>)[part];
      expect(value).toBe(original);
      paths.push(path.join("."));
      return value;
    },
  };
  renderToStaticMarkup(registry.render(block, "editor", editor));
  return paths;
}

function publication(
  blocks: SiteBlock[],
  pagePresentation?: PagePresentationV1 | PagePresentationV2,
) {
  return renderToStaticMarkup(
    renderPublishedPage(
      {
        kind: "publication",
        publicationId: "publication-1",
        snapshotHash: "b".repeat(64),
        locale: "en",
        designTokens: tokens,
        blocks,
        pagePresentation,
      },
      registry,
    ),
  );
}

describe("core.rich_text v2", () => {
  it("migrates v1 into one unchanged run and keeps the v1 markup", () => {
    const before = structuredClone(legacyRichText);
    const migrated = registry.migrate(legacyRichText);
    expect(legacyRichText).toEqual(before);
    // v1 -> v2 -> v3: the v3 step only copies.
    expect(migrated).toEqual({
      block_type: "core.rich_text",
      schema_version: 4,
      data: {
        content: [
          {
            type: "paragraph",
            content: [{ text: legacyRichText.data.text }],
          },
        ],
      },
    });
    const legacy = `<section class="site-block site-block--rich-text" data-block-type="core.rich_text"><p>${legacyRichText.data.text}</p></section>`;
    expect(renderToStaticMarkup(registry.render(legacyRichText, "a"))).toBe(
      legacy,
    );
    expect(renderToStaticMarkup(registry.render(migrated, "a"))).toBe(legacy);
    // Any mark, a second run, or a section field leaves the legacy shape.
    expect(
      renderToStaticMarkup(
        registry.render(
          richText({
            content: [
              { type: "paragraph", content: [{ text: "x", bold: true }] },
            ],
          }),
          "a",
        ),
      ),
    ).toContain('data-section-layout="column"');
    expect(
      renderToStaticMarkup(
        registry.render(
          richText({
            layout: "column",
            content: [{ type: "paragraph", content: [{ text: "x" }] }],
          }),
          "a",
        ),
      ),
    ).toContain("site-prose");
  });

  it("renders every node type as fixed semantic markup", () => {
    const html = publication([richText(article)]);
    expect(html).toContain(
      '<section class="site-block site-section site-section--rich_text site-section--chapters" data-block-type="core.rich_text" data-section-layout="chapters">',
    );
    expect(html).toContain(
      '<div class="site-section__intro"><h2>Poradnik</h2><p class="site-section__lead">Krótki wstęp.</p></div>',
    );
    expect(html).toContain(
      '<nav class="site-section__toc" aria-label="Contents"><ol><li><a href="#przygotowanie">Przygotowanie</a></li><li><a href="#przebieg">Przebieg</a></li></ol></nav>',
    );
    expect(html).toContain(
      '<p>Zwykły <strong>gruby</strong><em>pochyły</em><a class="site-prose__link" href="https://example.com/" rel="noreferrer"><strong><em>link</em></strong></a><a class="site-prose__link" href="#przebieg">kotwica</a></p>',
    );
    expect(html).toContain('<h2 id="przygotowanie">Przygotowanie</h2>');
    expect(html).toContain('<h3 id="narzedzia">Narzędzia</h3>');
    expect(html).toContain('<h4 id="detal">Detal</h4>');
    expect(html).toContain(
      "<ul><li>Pierwszy<ol><li>Podpunkt</li></ol></li><li>Drugi</li></ul>",
    );
    expect(html).toContain(
      '<figure class="site-quote"><blockquote><p>Mierz dwa razy.</p></blockquote><figcaption>Anna Nowak, <cite><a href="https://example.com/zrodlo" rel="noreferrer">Poradnik stolarza</a></cite></figcaption></figure>',
    );
    expect(html).toContain(
      '<div class="site-note site-note--warning" role="note"><strong class="site-note__title">Uwaga</strong><p>Wyłącz zasilanie.</p></div>',
    );
    expect(html).toContain(
      `<figure class="site-figure site-figure--wide"><img src="/media/${photo}" alt="Warsztat" loading="lazy" decoding="async"/><figcaption>Stanowisko pracy</figcaption></figure>`,
    );
    expect(html).toContain(
      '<aside class="site-section__aside"><h3>Najważniejsze</h3><p>Fakt pierwszy</p><ol><li>Krok</li></ol></aside>',
    );
    expect(html).not.toContain("style=");
  });

  it.each(["column", "split_intro", "facts_panel", "chapters"])(
    "renders every field in the %s layout, in reading order",
    (layout) => {
      const html = renderToStaticMarkup(
        registry.render(richText({ ...article, layout }), "block"),
      );
      for (const text of [
        "Poradnik",
        "Krótki wstęp.",
        "Wyłącz zasilanie.",
        "Stanowisko pracy",
        "Fakt pierwszy",
        "Detal",
      ])
        expect(html).toContain(text);
      const order = [
        "site-section__intro",
        "site-prose",
        "site-section__aside",
      ].map((name) => html.indexOf(name));
      expect(order).toEqual([...order].sort((a, b) => a - b));
      expect(html.includes("site-section__toc")).toBe(layout === "chapters");
      // Previews never emit ids: several can share one panel screen.
      expect(html).not.toContain(" id=");
    },
  );

  it("labels the index in the reader's language and defaults to Polish", () => {
    expect(
      renderToStaticMarkup(registry.render(richText(article), "block")),
    ).toContain('aria-label="Spis treści"');
  });

  it("maps every editable text to its exact, unique data path", () => {
    const paths = editorPaths(richText(article));
    expect(paths).toEqual([
      "title",
      "lead",
      "content.0.text",
      "content.1.content.0.text",
      "content.1.content.1.text",
      "content.1.content.2.text",
      "content.1.content.3.text",
      "content.1.content.4.text",
      "content.2.text",
      "content.3.items.0.content.0.text",
      "content.3.items.0.children.items.0.content.0.text",
      "content.3.items.1.content.0.text",
      "content.4.text",
      "content.5.source",
      "content.5.content.0.text",
      "content.5.author",
      "content.6.title",
      "content.6.content.0.text",
      "content.7.caption",
      "content.8.text",
      "aside.title",
      "aside.content.0.content.0.text",
      "aside.content.1.items.0.content.0.text",
    ]);
    expect(new Set(paths).size).toBe(paths.length);
    expect(editorPaths(legacyRichText)).toEqual(["content.0.content.0.text"]);
  });

  it("renders links as spans, headings as presentation and no ids in the editor", () => {
    const html = renderToStaticMarkup(
      registry.render(
        richText(article),
        "editor",
        { text: (_path, value) => value },
        undefined,
        undefined,
        { preview: false, locale: "en" },
      ),
    );
    expect(html).not.toContain("href=");
    expect(html).not.toContain(" id=");
    expect(html).toContain('<h2 role="presentation">Przygotowanie</h2>');
    expect(html).toContain('<span class="site-prose__link"><strong><em>link');
    expect(html).toContain("<li><span>Przebieg</span></li>");
  });

  it("escapes hostile text and rejects unsafe links in the schema", () => {
    const html = publication([
      richText({
        content: [
          {
            type: "paragraph",
            content: [{ text: "<script>alert(1)</script>", bold: true }],
          },
        ],
      }),
    ]);
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).not.toContain("<script>");
    for (const href of [
      "javascript:alert(1)",
      "//evil.example",
      "data:text/html,x",
      "#Bad Anchor",
    ])
      expect(() =>
        registry.validate(
          richText({
            content: [{ type: "paragraph", content: [{ text: "x", href }] }],
          }),
        ),
      ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        richText({ content: [{ type: "html", html: "<b>x</b>" }] }),
      ),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        richText({
          content: [{ type: "heading", level: 1, anchor: "a", text: "x" }],
        }),
      ),
    ).toThrow(InvalidBlockDataError);
  });

  it("reports only the issues of each node's own type", () => {
    const issues = (block: SiteBlock) => {
      try {
        registry.validate(block);
      } catch (error) {
        if (!(error instanceof InvalidBlockDataError)) throw error;
        return error.issues.map(
          (issue) => `${issue.path.join(".")} ${issue.keyword}`,
        );
      }
      return [];
    };
    // Without narrowing, the paragraph would also report a heading's missing
    // level and anchor, a list's items and a figure's image.
    expect(
      issues(
        richText({
          content: [
            { type: "paragraph", content: [{ text: "" }] },
            { type: "heading", level: 2, anchor: "Bad", text: "x" },
            { type: "embed", html: "x" },
          ],
          aside: { content: [{ type: "list", style: "bullet", items: [] }] },
        }),
      ).sort(),
    ).toEqual([
      "aside.content.0.items minItems",
      "content.0.content.0.text minLength",
      "content.1.anchor pattern",
      "content.2 oneOf",
    ]);
    // Array-level issues are not node issues and stay.
    expect(issues(richText({ content: [] }))).toEqual(["content minItems"]);
  });
});

describe("section presentation envelope", () => {
  const hero: SiteBlock = {
    block_type: "core.hero",
    schema_version: 5,
    data: { title: "Hello" },
  };

  it("adds classes to the block root, or to the decoration layer when present", () => {
    const plain = renderToStaticMarkup(registry.render(hero, "a"));
    expect(
      renderToStaticMarkup(
        registry.render({ ...hero, presentation: { schemaVersion: 1 } }, "a"),
      ),
    ).toBe(plain);
    expect(registry.migrate(hero)).not.toHaveProperty("presentation");

    const presented = renderToStaticMarkup(
      registry.render(
        {
          ...hero,
          presentation: { schemaVersion: 1, inner: "wide", surface: "inverse" },
        },
        "a",
      ),
    );
    expect(presented).toBe(
      plain.replace(
        'class="site-block site-block--hero"',
        'class="site-block site-block--hero site-presentation site-presentation--inner-wide site-presentation--surface-inverse"',
      ),
    );

    const decorated = renderToStaticMarkup(
      registry.render(
        {
          ...hero,
          decoration: { schemaVersion: 1, background: "tint" },
          presentation: { schemaVersion: 1, surface: "muted" },
        },
        "a",
      ),
    );
    expect(decorated).toMatch(
      /^<div class="site-decoration [^"]* site-presentation site-presentation--surface-muted" data-section-decoration="1">/,
    );
    expect(decorated).toContain('class="site-block site-block--hero"');
  });

  it("carries the envelope through migration and rejects anything outside it", () => {
    const presentation = {
      schemaVersion: 1 as const,
      inner: "narrow" as const,
    };
    const migrated = registry.migrate({
      block_type: "core.rich_text",
      schema_version: 1,
      data: { text: "x" },
      presentation,
    });
    expect(migrated.presentation).toEqual(presentation);
    expect(migrated.presentation).not.toBe(presentation);
    for (const invalid of [
      { schemaVersion: 3 },
      { schemaVersion: 1, anchor: "kontakt" },
      { schemaVersion: 2, anchor: "Kontakt" },
      { schemaVersion: 2, anchor: "#kontakt" },
      { schemaVersion: 2, inner: "100vw" },
      { schemaVersion: 1, inner: "100vw" },
      { schemaVersion: 1, surface: "#000" },
      { schemaVersion: 1, css: "position:fixed" },
    ]) {
      try {
        registry.validate({
          ...hero,
          presentation: invalid as unknown as SiteBlock["presentation"],
        });
        expect.fail("The presentation contract must reject this value");
      } catch (error) {
        expect(error).toBeInstanceOf(InvalidBlockDataError);
        expect(
          (error as InvalidBlockDataError).issues.every(
            (issue) => issue.scope === "presentation",
          ),
        ).toBe(true);
      }
    }
  });
});

describe("section anchors (presentation v2)", () => {
  const hero: SiteBlock = {
    block_type: "core.hero",
    schema_version: 6,
    data: { title: "Hello" },
  };
  const anchored: SiteBlock = {
    ...hero,
    presentation: { schemaVersion: 2, anchor: "kontakt" },
  };
  const published = { preview: false } as const;

  it("validates v1 and v2 envelopes", () => {
    registry.validate({ ...hero, presentation: { schemaVersion: 1 } });
    registry.validate({
      ...hero,
      presentation: { schemaVersion: 2, inner: "wide", surface: "muted" },
    });
    registry.validate(anchored);
  });

  it("puts the anchor id on the outermost element only in publications", () => {
    const plain = renderToStaticMarkup(registry.render(hero, "a"));
    // Preview and editor: no id, and nothing else changes either.
    expect(renderToStaticMarkup(registry.render(anchored, "a"))).toBe(plain);
    const editor: BlockEditor = { text: (_path, value) => value };
    expect(
      renderToStaticMarkup(
        registry.render(anchored, "a", editor, undefined, undefined, published),
      ),
    ).not.toContain("id=");

    const publicPlain = renderToStaticMarkup(
      registry.render(hero, "a", undefined, undefined, undefined, published),
    );
    expect(
      renderToStaticMarkup(
        registry.render(
          anchored,
          "a",
          undefined,
          undefined,
          undefined,
          published,
        ),
      ),
    ).toBe(publicPlain.replace("><h1>", ' id="kontakt"><h1>'));
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            ...anchored,
            presentation: {
              schemaVersion: 2,
              anchor: "kontakt",
              surface: "inverse",
            },
          },
          "a",
          undefined,
          undefined,
          undefined,
          published,
        ),
      ),
    ).toMatch(
      /^<section class="site-block site-block--hero site-presentation site-presentation--surface-inverse"[^>]* id="kontakt">/,
    );
    const decorated = renderToStaticMarkup(
      registry.render(
        { ...anchored, decoration: { schemaVersion: 1, background: "tint" } },
        "a",
        undefined,
        undefined,
        undefined,
        published,
      ),
    );
    expect(decorated).toMatch(
      /^<div class="site-decoration [^>]*id="kontakt">/,
    );
    expect(decorated.match(/id="kontakt"/g)).toHaveLength(1);

    // A block that delegates to another component (contact v2 layouts)
    // still gets its classes and id on the HTML root.
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            block_type: "core.contact",
            schema_version: 2,
            data: { layout: "cards", title: "Kontakt", email: "a@b.pl" },
            presentation: {
              schemaVersion: 2,
              anchor: "kontakt",
              surface: "accent",
            },
          },
          "a",
          undefined,
          undefined,
          undefined,
          published,
        ),
      ),
    ).toMatch(
      /^<section class="site-block site-contact site-contact--cards site-presentation site-presentation--surface-accent"[^>]* id="kontakt">/,
    );

    const document = {
      blocks: [anchored],
      designTokens: tokens,
    };
    expect(publication(document.blocks)).toContain('id="kontakt"');
    expect(
      renderToStaticMarkup(
        renderDraftPreview(
          { kind: "draft-preview", versionId: "draft", ...document },
          registry,
        ),
      ),
    ).not.toContain('id="kontakt"');
  });
});

describe("secondary actions (hero v6, product v2)", () => {
  const editor: BlockEditor = { text: (_path, value) => value };
  const heroLayouts = (
    heroV6Schema as { properties: { layout: { enum: string[] } } }
  ).properties.layout.enum;
  const actions = {
    action: { label: "Napisz do nas", href: "#kontakt" },
    secondaryAction: { label: "Zobacz ofertę", href: "https://example.com/" },
  };
  const row =
    '<div class="site-section__actions"><a class="site-section__action" href="#kontakt">Napisz do nas</a><a class="site-section__action site-section__action--secondary" href="https://example.com/" rel="noreferrer">Zobacz ofertę</a></div>';
  const editorRow =
    '<div class="site-section__actions"><span class="site-section__action">Napisz do nas</span><span class="site-section__action site-section__action--secondary">Zobacz ofertę</span></div>';
  const render = (block: SiteBlock, withEditor = false) =>
    renderToStaticMarkup(
      registry.render(
        block,
        "a",
        withEditor ? editor : undefined,
        undefined,
        undefined,
        { preview: false },
      ),
    );

  it("renders the quiet action beside the primary one in every hero layout", () => {
    for (const layout of [undefined, ...heroLayouts]) {
      const data: JsonObject = {
        title: "Hello",
        text: "Tekst",
        ...(layout ? { layout } : {}),
        image: { asset_id: photo, alt: "Zdjęcie" },
      };
      const hero = (extra: JsonObject): SiteBlock => ({
        block_type: "core.hero",
        schema_version: 6,
        data: { ...data, ...extra },
      });
      const both = render(hero(actions));
      // Layout variants have always written href before class (kept as is).
      expect(
        both.replace(
          'href="#kontakt" class="site-section__action"',
          'class="site-section__action" href="#kontakt"',
        ),
        layout,
      ).toContain(row);
      expect(render(hero(actions), true), layout).toContain(editorRow);

      // Without the quiet action the markup is exactly the v5 markup.
      const primary = { action: { label: "Oferta", href: "/oferta/" } };
      const v6 = render(hero(primary));
      expect(v6).not.toContain("site-section__actions");
      expect(v6).toBe(render({ ...hero(primary), schema_version: 5 }));
      // Only the quiet action: the row holds just that one.
      expect(
        render(hero({ secondaryAction: actions.secondaryAction })),
      ).toContain(
        '<div class="site-section__actions"><a class="site-section__action site-section__action--secondary"',
      );
    }
  });

  it("renders the product's quiet action and migrates v1 unchanged", () => {
    const v1: SiteBlock = {
      block_type: "core.product",
      schema_version: 1,
      data: {
        title: "Lutownica",
        action: { label: "Oferta", href: "/oferta/" },
      },
    };
    expect(registry.migrate(v1)).toEqual({ ...v1, schema_version: 2 });
    expect(render(v1)).not.toContain("site-section__actions");
    const v2: SiteBlock = {
      ...v1,
      schema_version: 2,
      data: { ...v1.data, ...actions },
    };
    expect(render(v2)).toContain(row);
    expect(render(v2, true)).toContain(editorRow);
    expect(() =>
      registry.validate({
        ...v1,
        data: { ...v1.data, secondaryAction: actions.secondaryAction },
      }),
    ).toThrow(InvalidBlockDataError);
  });

  it("offers the quiet action in the catalogue", () => {
    for (const type of ["core.hero", "core.product"])
      expect(
        registry.definitions
          .get(type)!
          .catalog!.fields.filter(({ path }) => path[0] === "secondaryAction")
          .map(({ labelKey }) => labelKey),
      ).toEqual(["secondaryActionLabel", "secondaryActionHref"]);
  });
});

describe("page presentation", () => {
  it("adds its classes to the themed element of drafts and publications", () => {
    const value: PagePresentationV1 = {
      schemaVersion: 1,
      width: "full",
      headingFont: "playfair-display",
      bodyFont: "inter",
    };
    expect(pagePresentationClassName(value)).toBe(
      "site-page--full site-heading-font--playfair-display site-body-font--inter",
    );
    expect(
      pagePresentationClassName({ schemaVersion: 1, width: "contained" }),
    ).toBe("");
    expect(pagePresentationClassName(null)).toBe("");
    expect(pagePresentationClassName(undefined)).toBe("");
    for (const invalid of [
      { schemaVersion: 1, width: "100vw" },
      { schemaVersion: 1, bodyFont: "Comic Sans" },
      { width: "full" },
    ])
      expect(() =>
        pagePresentationClassName(invalid as unknown as PagePresentationV1),
      ).toThrow(TypeError);

    const blocks = [legacyRichText];
    expect(publication(blocks, value)).toContain(
      '<div class="site-theme site-theme--blue site-theme--sans site-theme--radius-medium site-theme--comfortable site-page--full site-heading-font--playfair-display site-body-font--inter">',
    );
    const draft = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft",
          blocks,
          designTokens: tokens,
          pagePresentation: { schemaVersion: 1, width: "full" },
        },
        registry,
      ),
    );
    expect(draft).toContain("site-page--full site-theme--preview");
    expect(publication(blocks)).not.toContain("site-page");
  });

  it("adds the v2 page style class and leaves the rest as in v1", () => {
    const v1: PagePresentationV1 = {
      schemaVersion: 1,
      width: "full",
      headingFont: "lora",
    };
    expect(pagePresentationClassName({ ...v1, schemaVersion: 2 })).toBe(
      pagePresentationClassName(v1),
    );
    expect(
      pagePresentationClassName({ ...v1, schemaVersion: 2, style: "premium" }),
    ).toBe("site-page--full site-heading-font--lora site-style--premium");
    expect(
      publication([legacyRichText], { schemaVersion: 2, style: "technical" }),
    ).toContain("site-theme--comfortable site-style--technical");
    for (const invalid of [
      { schemaVersion: 2, style: "brutalist" },
      { schemaVersion: 1, style: "editorial" },
    ])
      expect(() =>
        pagePresentationClassName(invalid as unknown as PagePresentationV2),
      ).toThrow(TypeError);
  });
});

describe("heading anchors", () => {
  const section = (anchors: string[], href?: string): SiteBlock =>
    richText({
      content: [
        ...anchors.map((anchor) => ({
          type: "heading",
          level: 2,
          anchor,
          text: anchor,
        })),
        {
          type: "paragraph",
          content: [{ text: "link", ...(href ? { href } : {}) }],
        },
      ],
      aside: {
        content: [
          {
            type: "paragraph",
            content: [{ text: "aside", ...(href ? { href } : {}) }],
          },
        ],
      },
    });

  it("renames later duplicates with their own links, without mutating input", () => {
    const blocks = [
      section(["plan"]),
      { block_type: "core.hero", schema_version: 5, data: { title: "x" } },
      section(["plan", "koszty"], "#plan"),
      section(["plan", "plan"], "#plan"),
    ];
    const before = structuredClone(blocks);
    const unique = ensureUniqueAnchors(blocks, new Set(["koszty"]));
    expect(blocks).toEqual(before);
    expect(unique[0]).toBe(blocks[0]);
    expect(unique[1]).toBe(blocks[1]);
    expect(richTextAnchors(unique)).toEqual([
      "plan",
      "plan-2",
      "koszty-2",
      "plan-3",
      "plan-4",
    ]);
    // The renamed section's links follow its own heading…
    expect(JSON.stringify(unique[2]!.data)).not.toContain('"#plan"');
    expect(JSON.stringify(unique[2]!.data).match(/#plan-2/g)).toHaveLength(2);
    // …but links to an anchor the section still owns stay put.
    expect(JSON.stringify(unique[3]!.data)).toContain('"#plan-3"');
    for (const block of unique) registry.validate(block);
    expect(ensureUniqueAnchors(unique)).toEqual(unique);
  });

  it("shares one namespace with section anchors and renames them the same way", () => {
    const hero: SiteBlock = {
      block_type: "core.hero",
      schema_version: 6,
      data: {
        title: "x",
        action: { label: "a", href: "#kontakt" },
        secondaryAction: { label: "b", href: "#kontakt" },
      },
      presentation: { schemaVersion: 2, anchor: "kontakt", surface: "muted" },
    };
    const product: SiteBlock = {
      block_type: "core.product",
      schema_version: 2,
      data: { title: "y", action: { label: "a", href: "#kontakt" } },
      presentation: { schemaVersion: 2, anchor: "oferta" },
    };
    // A section owning an anchor one of its own headings repeats.
    const own: SiteBlock = {
      ...section(["plan"], "#plan"),
      presentation: { schemaVersion: 2, anchor: "plan" },
    };
    const v1: SiteBlock = {
      ...section(["v1"]),
      presentation: { schemaVersion: 1, inner: "wide" },
    };
    const blocks = [section(["kontakt"]), hero, product, own, v1];
    const before = structuredClone(blocks);
    expect(richTextAnchors(blocks)).toEqual([
      "kontakt",
      "kontakt",
      "oferta",
      "plan",
      "plan",
      "v1",
    ]);

    const unique = ensureUniqueAnchors(blocks);
    expect(blocks).toEqual(before);
    expect(unique[0]).toBe(blocks[0]);
    expect(unique[2]).toBe(blocks[2]);
    expect(unique[4]).toBe(blocks[4]);
    expect(richTextAnchors(unique)).toEqual([
      "kontakt",
      "kontakt-2",
      "oferta",
      "plan",
      "plan-2",
      "v1",
    ]);
    // The renamed hero keeps the rest of its envelope; its actions follow.
    expect(unique[1]!.presentation).toEqual({
      schemaVersion: 2,
      anchor: "kontakt-2",
      surface: "muted",
    });
    expect(unique[1]!.data).toMatchObject({
      action: { href: "#kontakt-2" },
      secondaryAction: { href: "#kontakt-2" },
    });
    // The section still owns "plan", so its links keep pointing at it.
    expect(JSON.stringify(unique[3]!.data)).toContain('"#plan"');
    for (const block of unique) registry.validate(block);
    expect(ensureUniqueAnchors(unique)).toEqual(unique);
    expect(
      richTextAnchors(ensureUniqueAnchors([hero], new Set(["kontakt"]))),
    ).toEqual(["kontakt-2"]);
  });
});

describe("template media", () => {
  const block = (data: JsonObject): SiteBlock => ({
    block_type: "core.product",
    schema_version: 1,
    data,
  });
  const binding = {
    blockPosition: 0,
    mediaId: "electronics",
    alt: { pl: "Zdjęcie", en: "Photo" },
  };

  it("binds by legacy and nested paths, appends, and never mutates", () => {
    const blocks: SiteBlock[] = [
      {
        block_type: "core.hero",
        schema_version: 5,
        data: { title: "x" },
      },
      block({ title: "Produkt", images: [] }),
    ];
    const before = structuredClone(blocks);
    const bound = bindTemplateMedia(
      blocks,
      [
        { ...binding },
        { ...binding, blockPosition: 1, path: ["images", 0] },
        { ...binding, blockPosition: 1, path: ["images", 1] },
      ],
      (index, mediaId) => `${mediaId}-${index}`,
      "en",
    );
    expect(blocks).toEqual(before);
    expect(bound[0]!.data.image).toEqual({
      asset_id: "electronics-0",
      alt: "Photo",
    });
    expect(bound[1]!.data.images).toEqual([
      { asset_id: "electronics-1", alt: "Photo" },
      { asset_id: "electronics-2", alt: "Photo" },
    ]);
    const id = () => photo;
    for (const invalid of [
      { ...binding, blockPosition: 5 },
      { ...binding, blockPosition: 1, path: ["images", 3] },
      { ...binding, blockPosition: 1, path: ["missing", "image"] },
    ])
      expect(() => bindTemplateMedia(blocks, [invalid], id, "pl")).toThrow(
        TypeError,
      );
  });

  it("seeds recipe blocks with preview photos, envelopes and validation after binding", () => {
    expect(templatePreviewAssetId(3)).toBe(
      "00000000-0000-4000-8000-000000000003",
    );
    const template: PageTemplate = {
      id: "core.test_recipe",
      version: 1,
      category: "product",
      labels: {
        pl: { name: "x", description: "x" },
        en: { name: "x", description: "x" },
      },
      mediaBindings: [
        { ...binding, path: ["images", 0] },
        { ...binding, path: ["images", 1] },
      ],
      blocks: [
        {
          ...block({ title: "Produkt", images: [] }),
          decoration: { schemaVersion: 1, background: "tint" },
          presentation: { schemaVersion: 1, inner: "wide" },
        },
      ],
    };
    const [seeded] = pageTemplateBlocks(template, registry, "pl");
    expect(seeded!.data.images).toEqual([
      { asset_id: templatePreviewAssetId(0), alt: "Zdjęcie" },
      { asset_id: templatePreviewAssetId(1), alt: "Zdjęcie" },
    ]);
    expect(seeded!.decoration).toEqual({
      schemaVersion: 1,
      background: "tint",
    });
    expect(seeded!.presentation).toEqual({ schemaVersion: 1, inner: "wide" });
    expect(template.blocks[0]!.data.images).toEqual([]);
    expect(blockAssetIds(seeded!.data)).toEqual([
      templatePreviewAssetId(0),
      templatePreviewAssetId(1),
    ]);
    expect(() =>
      pageTemplateBlocks(
        { ...template, mediaBindings: [{ ...binding, path: ["nope", 0] }] },
        registry,
      ),
    ).toThrow(InvalidPageTemplateError);
  });

  it("puts a section's sample photo at its path", () => {
    const template = coreSectionTemplates().find(
      (item) => item.id === "core.product_showcase",
    )!;
    const seeded = sectionTemplateBlock(template, "en", registry);
    const before = structuredClone(seeded);
    const withPhoto = applySampleMedia(seeded, template, photo, "en");
    expect(seeded).toEqual(before);
    expect((withPhoto.data.images as JsonObject[])[0]).toEqual({
      asset_id: photo,
      alt: template.sampleMedia!.alt.en,
    });
    registry.validate(withPhoto);

    const hero = coreSectionTemplates().find(
      (item) => item.blockType === "core.hero" && item.sampleMedia,
    )!;
    const heroBlock = applySampleMedia(
      sectionTemplateBlock(hero, "pl", registry),
      hero,
      photo,
      "pl",
    );
    expect(heroBlock.data.image).toEqual({
      asset_id: photo,
      alt: hero.sampleMedia!.alt.pl,
    });
    const plain = coreSectionTemplates().find((item) => !item.sampleMedia)!;
    const plainBlock = sectionTemplateBlock(plain, "pl", registry);
    expect(applySampleMedia(plainBlock, plain, photo, "pl")).toBe(plainBlock);
  });
});

describe("feature_list v4", () => {
  it("renders lead and note in every layout, including the legacy markup", () => {
    const data = {
      title: "Oferta",
      lead: "Wstęp do listy",
      items: [{ title: "Pozycja", text: "Opis" }],
      note: { title: "Ważne", text: "Treść uwagi" },
    };
    const layouts = [
      undefined,
      ...new Set(
        coreSectionTemplates()
          .filter((item) => item.blockType === "core.feature_list")
          .map((item) => item.layout),
      ),
    ];
    expect(layouts).toContain("steps_notes");
    for (const layout of layouts) {
      const block: SiteBlock = {
        block_type: "core.feature_list",
        schema_version: 4,
        data: layout ? { ...data, layout } : data,
      };
      const html = renderToStaticMarkup(registry.render(block, "b"));
      for (const text of [
        "Oferta",
        "Wstęp do listy",
        "Opis",
        "Ważne",
        "Treść uwagi",
      ])
        expect(html).toContain(text);
      const paths = editorPaths(block);
      expect(new Set(paths).size).toBe(paths.length);
    }
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            block_type: "core.feature_list",
            schema_version: 4,
            data: { ...data, layout: "benefits_commentary" },
          },
          "b",
        ),
      ),
    ).toMatch(
      /<\/ul><div class="site-section__commentary"><p class="site-section__lead">Wstęp do listy<\/p><aside class="site-section__note"><h3>Ważne<\/h3><p>Treść uwagi<\/p><\/aside><\/div><\/section>$/,
    );
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            block_type: "core.feature_list",
            schema_version: 4,
            data: { ...data, layout: "steps_notes" },
          },
          "b",
        ),
      ),
    ).toContain(
      '<ol><li><span class="site-section__step" aria-hidden="true">01</span>',
    );
  });
});

describe("core.quote and core.product", () => {
  const quote = (data: JsonObject): SiteBlock => ({
    block_type: "core.quote",
    schema_version: 1,
    data,
  });
  const cited = {
    quote: "Jakość to nawyk.",
    author: "Jan Kowalski",
    role: "Mistrz cechu",
    source: { label: "Wywiad", href: "https://example.com/wywiad" },
    context: "Rozmowa z 2024 roku.",
  };

  it("renders the typographic quote and links the source only when published", () => {
    const html = publication([quote(cited)]);
    expect(html).toContain(
      '<section class="site-block site-section site-section--quote site-section--typographic" data-block-type="core.quote"><figure class="site-quote site-quote--large"><blockquote><p>Jakość to nawyk.</p></blockquote><figcaption><span class="site-quote__author">Jan Kowalski</span><span class="site-quote__role">Mistrz cechu</span><cite><a href="https://example.com/wywiad" rel="noreferrer">Wywiad</a></cite></figcaption></figure><p class="site-quote__context">Rozmowa z 2024 roku.</p></section>',
    );
    const preview = renderToStaticMarkup(registry.render(quote(cited), "q"));
    expect(preview).toContain("<cite>Wywiad</cite>");
    expect(editorPaths(quote(cited))).toEqual([
      "author",
      "role",
      "source.label",
      "quote",
      "context",
    ]);
  });

  it("shows the portrait, or an initials monogram hidden from assistive tech", () => {
    const withPhoto = renderToStaticMarkup(
      registry.render(
        quote({
          ...cited,
          layout: "portrait",
          image: { asset_id: photo, alt: "Jan" },
        }),
        "q",
      ),
    );
    expect(withPhoto).toContain('data-section-layout="portrait"');
    expect(withPhoto).toContain(
      `<div class="site-quote__portrait"><img src="/media/${photo}" alt="Jan" loading="lazy" decoding="async"/></div>`,
    );
    expect(
      renderToStaticMarkup(
        registry.render(quote({ ...cited, layout: "portrait" }), "q"),
      ),
    ).toContain(
      '<span class="site-quote__monogram" aria-hidden="true">JK</span>',
    );
    expect(
      renderToStaticMarkup(
        registry.render(
          quote({
            ...cited,
            layout: "portrait",
            image: { asset_id: photo, alt: "Jan" },
          }),
          "q",
          undefined,
          (image) => `adapter:${image.asset_id}`,
        ),
      ),
    ).toContain(`adapter:${photo}`);
  });

  const product: SiteBlock = {
    block_type: "core.product",
    schema_version: 1,
    data: {
      layout: "showcase",
      title: "Lutownica",
      tagline: "Precyzja na co dzień",
      text: "Pierwszy akapit.\n\nDrugi akapit.",
      images: [
        { asset_id: photo, alt: "Przód", caption: "Widok z przodu" },
        { asset_id: other, alt: "Bok", caption: "Widok z boku" },
      ],
      specs: [{ label: "Moc", value: "60 W" }],
      uses: [{ title: "Serwis", text: "Naprawy płytek." }],
      action: { label: "Zapytaj", href: "/kontakt/" },
    },
  };

  it("renders the showcase with gallery, paragraphs, specs, uses and action", () => {
    const html = publication([product]);
    expect(html).toContain('data-section-layout="showcase"');
    expect(html).toContain(
      `<div class="site-product__gallery"><figure class="site-product__photo"><img src="/media/${photo}" alt="Przód" loading="lazy" decoding="async"/><figcaption>Widok z przodu</figcaption></figure><ul class="site-product__strip"><li><figure><img src="/media/${other}" alt="Bok" loading="lazy" decoding="async"/><figcaption>Widok z boku</figcaption></figure></li></ul></div>`,
    );
    expect(html).toContain(
      '<div class="site-product__text"><p>Pierwszy akapit.</p><p>Drugi akapit.</p></div>',
    );
    expect(html).toContain(
      '<dl class="site-product__specs"><div><dt>Moc</dt><dd>60 W</dd></div></dl>',
    );
    expect(html).toContain(
      '<a class="site-section__action" href="/kontakt/">Zapytaj</a>',
    );
    expect(html).not.toMatch(/price|cena/i);
    expect(blockAssetIds(product.data)).toEqual([photo, other]);
  });

  it("edits the description as one field and the action as a span", () => {
    expect(editorPaths(product)).toEqual([
      "title",
      "tagline",
      "images.0.caption",
      "images.1.caption",
      "text",
      "specs.0.label",
      "specs.0.value",
      "uses.0.title",
      "uses.0.text",
      "action.label",
    ]);
    const html = renderToStaticMarkup(
      registry.render(product, "p", { text: (_path, value) => value }),
    );
    expect(html).toContain('<span class="site-section__action">Zapytaj</span>');
    expect(html).not.toContain("href=");
    expect(html).toContain('<h2 role="presentation">Lutownica</h2>');
  });

  it("collects every asset id of real blocks", () => {
    expect(blockAssetIds(article)).toEqual([photo]);
    expect(
      blockAssetIds({
        ...cited,
        layout: "portrait",
        image: { asset_id: other, alt: "x" },
      }),
    ).toEqual([other]);
  });
});
