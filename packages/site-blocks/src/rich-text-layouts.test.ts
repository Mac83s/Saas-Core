import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  InvalidBlockDataError,
  type BlockEditor,
  type JsonObject,
  type RichTextNode,
  type RichTextV3Layout,
  type SiteBlock,
} from "./index";
import { richTextChapters } from "./rich-text-block";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const photo = "11111111-2222-4333-8444-555555555555";
const sketch = "22222222-3333-4444-8555-666666666666";
const portrait = "66666666-7777-4888-8999-000000000000";

const LAYOUTS: RichTextV3Layout[] = [
  "lead_statement",
  "two_parts",
  "side_photo",
  "panorama",
  "illustrated",
  "margin_quote",
  "summary_box",
  "expert_note",
  "alternating_chapters",
  "timeline",
  "numbered_sections",
  "manifesto",
  "problem_solution",
  "howto",
  "resources",
  "essay_cta",
];

/** Every v3 field, an intro before the first H2 and four chapters. */
const full: JsonObject = {
  eyebrow: "Dla właścicieli",
  title: "Jak pracujemy",
  lead: "Teza sekcji.",
  content: [
    { type: "paragraph", content: [{ text: "Wstęp przed rozdziałami." }] },
    { type: "heading", level: 2, anchor: "dla-kogo", text: "Dla kogo" },
    {
      type: "list",
      style: "bullet",
      items: [
        {
          content: [
            { text: "Cennik PDF", href: "/cennik.pdf" },
            { text: " — opis materiału" },
          ],
        },
        { content: [{ text: "Zasada bez linku" }] },
      ],
    },
    { type: "heading", level: 2, anchor: "dla-kogo-nie", text: "Dla kogo nie" },
    {
      type: "quote",
      content: [{ text: "Cytat na marginesie." }],
      author: "Klient",
    },
    {
      type: "list",
      style: "ordered",
      items: [{ content: [{ text: "Krok pierwszy" }] }],
    },
    { type: "heading", level: 2, anchor: "rozwiazanie", text: "Rozwiązanie" },
    {
      type: "figure",
      image: { asset_id: sketch, alt: "Szkic" },
      caption: "Podpis ilustracji",
      width: "wide",
    },
    {
      type: "note",
      tone: "tip",
      title: "Wskazówka",
      content: [{ text: "Treść uwagi." }],
    },
    { type: "heading", level: 2, anchor: "dalej", text: "Dalej" },
    { type: "paragraph", content: [{ text: "Czwarty rozdział." }] },
  ],
  image: { asset_id: photo, alt: "Zespół", caption: "Podpis zdjęcia" },
  author: { name: "Anna Nowak", role: "Lekarz weterynarii" },
  aside: {
    title: "W skrócie",
    content: [{ type: "paragraph", content: [{ text: "Fakt z panelu." }] }],
  },
  action: { label: "Umów wizytę", href: "#kontakt" },
  secondaryAction: {
    label: "Zobacz cennik",
    href: "https://example.com/cennik",
  },
};
const TEXTS = [
  "Dla właścicieli",
  "Jak pracujemy",
  "Teza sekcji.",
  "Wstęp przed rozdziałami.",
  "Cennik PDF",
  "Zasada bez linku",
  "Cytat na marginesie.",
  "Krok pierwszy",
  "Podpis ilustracji",
  "Treść uwagi.",
  "Czwarty rozdział.",
  "Podpis zdjęcia",
  "Anna Nowak",
  "Lekarz weterynarii",
  "W skrócie",
  "Fakt z panelu.",
  "Umów wizytę",
  "Zobacz cennik",
];
const PATHS = [
  "eyebrow",
  "title",
  "lead",
  "content.0.content.0.text",
  "content.1.text",
  "content.2.items.0.content.0.text",
  "content.2.items.0.content.1.text",
  "content.2.items.1.content.0.text",
  "content.3.text",
  "content.4.content.0.text",
  "content.4.author",
  "content.5.items.0.content.0.text",
  "content.6.text",
  "content.7.caption",
  "content.8.title",
  "content.8.content.0.text",
  "content.9.text",
  "content.10.content.0.text",
  "image.caption",
  "author.name",
  "author.role",
  "aside.title",
  "aside.content.0.content.0.text",
  "action.label",
  "secondaryAction.label",
];

const block = (data: JsonObject, schema_version = 3): SiteBlock => ({
  block_type: "core.rich_text",
  schema_version,
  data,
});
const preview = (data: JsonObject) =>
  renderToStaticMarkup(registry.render(block(data), "b"));
const published = (data: JsonObject) =>
  renderToStaticMarkup(
    registry.render(block(data), "b", undefined, undefined, undefined, {
      preview: false,
      locale: "pl",
    }),
  );
const at = (html: string, needle: string) => {
  const index = html.indexOf(needle);
  expect(index, needle).toBeGreaterThanOrEqual(0);
  return index;
};

function editorPaths(data: JsonObject): { paths: string[]; html: string } {
  const paths: string[] = [];
  const editor: BlockEditor = {
    text: (path, value) => {
      let original: unknown = data;
      for (const part of path)
        original = (original as Record<string, unknown>)[part];
      expect(value).toBe(original);
      paths.push(path.join("."));
      return value;
    },
  };
  const html = renderToStaticMarkup(
    registry.render(block(data), "editor", editor, undefined, undefined, {
      preview: false,
    }),
  );
  return { paths, html };
}

describe("core.rich_text v3", () => {
  it("migrates v2 by copying and keeps the v1 markup for a bare paragraph", () => {
    const v2 = block(
      {
        layout: "facts_panel",
        title: "Tytuł",
        content: [{ type: "paragraph", content: [{ text: "x" }] }],
      },
      2,
    );
    const before = structuredClone(v2);
    const migrated = registry.migrate(v2);
    expect(v2).toEqual(before);
    expect(migrated).toEqual({ ...before, schema_version: 4 });
    expect(migrated.data).not.toBe(v2.data);

    const legacy =
      '<section class="site-block site-block--rich-text" data-block-type="core.rich_text"><p>Zwykły tekst</p></section>';
    const bare = {
      content: [{ type: "paragraph", content: [{ text: "Zwykły tekst" }] }],
    };
    expect(preview(bare)).toBe(legacy);
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            block_type: "core.rich_text",
            schema_version: 1,
            data: { text: "Zwykły tekst" },
          },
          "b",
        ),
      ),
    ).toBe(legacy);
    // Any v3 field leaves the legacy shape.
    for (const extra of [
      { eyebrow: "E" },
      { action: { label: "A", href: "/a/" } },
      { author: { name: "A" } },
      { image: { asset_id: photo, alt: "x" } },
    ] as JsonObject[])
      expect(preview({ ...bare, ...extra })).toContain(
        'data-section-layout="column"',
      );
  });

  it("keeps v2 layouts' markup and adds v3 fields after the text", () => {
    const html = published({ ...full, layout: "column" });
    expect(html).toContain(
      '<div class="site-section__intro"><p class="site-section__eyebrow">Dla właścicieli</p><h2>Jak pracujemy</h2><p class="site-section__lead">Teza sekcji.</p></div>',
    );
    expect(html).toContain(
      `<figure class="site-section__image"><img src="/media/${photo}" alt="Zespół" loading="lazy" decoding="async"/><figcaption>Podpis zdjęcia</figcaption></figure>`,
    );
    expect(html).toContain(
      '<div class="site-author"><span class="site-author__monogram" aria-hidden="true">AN</span><div class="site-author__text"><p class="site-author__name">Anna Nowak</p><p class="site-author__role">Lekarz weterynarii</p></div></div>',
    );
    expect(html).toMatch(
      /<div class="site-section__actions"><a class="site-section__action" href="#kontakt">Umów wizytę<\/a><a class="site-section__action site-section__action--secondary" href="https:\/\/example.com\/cennik" rel="noreferrer">Zobacz cennik<\/a><\/div><\/section>$/,
    );
    const order = [
      "site-section__intro",
      "site-prose",
      "site-section__image",
      "site-author",
      "site-section__aside",
      "site-section__actions",
    ].map((name) => at(html, name));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    for (const layout of ["split_intro", "facts_panel", "chapters"])
      for (const text of TEXTS)
        expect(preview({ ...full, layout })).toContain(text);
  });

  it.each(LAYOUTS)("renders every field in %s", (layout) => {
    const html = preview({ ...full, layout });
    expect(html).toContain(
      `<section class="site-block site-section site-section--rich_text site-section--${layout}" data-block-type="core.rich_text" data-section-layout="${layout}">`,
    );
    for (const text of TEXTS) expect(html).toContain(text);
    expect(html).toContain(`src="/media/${photo}"`);
    expect(html).toContain(`src="/media/${sketch}"`);
    expect(html).toContain("site-section__eyebrow");
    expect(html).not.toContain("style=");
    expect(html).not.toContain(" id=");
    // The intro always opens the section, except under a panorama.
    if (layout !== "panorama")
      expect(html).toContain(
        `data-section-layout="${layout}"><div class="site-section__intro">`,
      );
  });

  it("gives each layout its own structure, in reading order", () => {
    const html = (layout: RichTextV3Layout) => preview({ ...full, layout });
    const inOrder = (source: string, ...needles: string[]) => {
      const positions = needles.map((needle) => at(source, needle));
      expect(positions).toEqual([...positions].sort((a, b) => a - b));
    };
    for (const layout of [
      "lead_statement",
      "howto",
      "resources",
      "essay_cta",
      "margin_quote",
    ] as const)
      inOrder(
        html(layout),
        "site-section__intro",
        '<div class="site-prose">',
        "site-section__image",
        "site-author",
        "site-section__aside",
        "site-section__actions",
      );

    const twoParts = html("two_parts");
    expect(twoParts).toContain(
      '<div class="site-prose"><p>Wstęp przed rozdziałami.</p></div><div class="site-section__parts"><div class="site-chapter"><div class="site-prose"><h2>Dla kogo</h2>',
    );
    expect(twoParts).toContain(
      '</div></div></div><div class="site-prose"><h2>Rozwiązanie</h2>',
    );
    expect(twoParts.match(/class="site-chapter"/g)).toHaveLength(2);

    expect(html("side_photo")).toMatch(
      /<\/div><figure class="site-section__image">.*<\/figure><div class="site-section__main"><div class="site-prose">.*<div class="site-author">.*<aside class="site-section__aside">.*<div class="site-section__actions">.*<\/div><\/div><\/section>$/,
    );
    expect(html("panorama")).toContain(
      'data-section-layout="panorama"><figure class="site-section__image">',
    );
    expect(html("illustrated")).toContain(
      '<div class="site-prose"><p>Wstęp przed rozdziałami.</p><figure class="site-section__image">',
    );
    expect(html("summary_box")).toContain(
      '</div><aside class="site-section__aside"><h3>W skrócie</h3><p>Fakt z panelu.</p></aside><div class="site-prose">',
    );
    expect(html("expert_note")).toMatch(
      /<div class="site-section__expert"><div class="site-author">.*<\/div><div class="site-section__actions">.*<\/div><\/div><div class="site-section__main"><div class="site-prose">.*<figure class="site-section__image">.*<aside class="site-section__aside">.*<\/aside><\/div><\/section>$/,
    );

    const alternating = html("alternating_chapters");
    expect(alternating).toContain(
      '<div class="site-chapters"><div class="site-chapter"><div class="site-chapter__head"><h2>Dla kogo</h2></div><div class="site-prose"><ul>',
    );
    // The chapter's illustration joins the heading's side.
    expect(alternating).toContain(
      '<div class="site-chapter__head"><h2>Rozwiązanie</h2><figure class="site-figure site-figure--wide">',
    );
    expect(alternating).toContain(
      '</figure></div><div class="site-prose"><div class="site-note site-note--tip"',
    );

    const timeline = html("timeline");
    expect(timeline).toContain(
      '<ol class="site-chapters"><li class="site-chapter"><div class="site-prose"><h2>Dla kogo</h2>',
    );
    expect(timeline.match(/<li class="site-chapter">/g)).toHaveLength(4);
    expect(timeline).not.toContain("site-chapter__number");

    const numbered = html("numbered_sections");
    for (const [number, heading] of [
      ["01", "Dla kogo"],
      ["04", "Dalej"],
    ])
      expect(numbered).toContain(
        `<li class="site-chapter"><span class="site-chapter__number" aria-hidden="true">${number}</span><div class="site-prose"><h2>${heading}</h2>`,
      );

    inOrder(
      html("manifesto"),
      '<div class="site-prose">',
      "site-section__actions",
      "site-section__image",
      "site-author",
      "site-section__aside",
    );

    const problem = html("problem_solution");
    expect(problem.match(/<div class="site-chapter">/g)).toHaveLength(3);
    // The action closes the solution panel; the fourth chapter follows.
    expect(problem).toMatch(
      /<h2>Rozwiązanie<\/h2>.*<\/div><div class="site-section__actions">.*<\/div><\/div><\/div><div class="site-prose"><h2>Dalej<\/h2>/,
    );
    expect(problem.match(/site-section__actions/g)).toHaveLength(1);
  });

  it("renders the margin quote once, in reading position", () => {
    const html = preview({ ...full, layout: "margin_quote" });
    expect(html.match(/Cytat na marginesie\./g)).toHaveLength(1);
    expect(html).toContain(
      '<h2>Dla kogo nie</h2><figure class="site-quote site-quote--margin"><blockquote><p>Cytat na marginesie.</p>',
    );
    expect(preview({ ...full, layout: "column" })).not.toContain(
      "site-quote--margin",
    );
  });

  it.each(["column", ...LAYOUTS])(
    "maps every editable text of %s to its exact, unique path",
    (layout) => {
      const { paths, html } = editorPaths({ ...full, layout });
      expect([...paths].sort()).toEqual([...PATHS].sort());
      expect(new Set(paths).size).toBe(paths.length);
      expect(html).not.toContain("href=");
      expect(html).not.toContain(" id=");
      expect(html).toContain(
        '<span class="site-section__action">Umów wizytę</span><span class="site-section__action site-section__action--secondary">Zobacz cennik</span>',
      );
      expect(html).toContain('<span class="site-prose__link">Cennik PDF');
      expect(html).toContain('role="presentation"');
    },
  );

  it("emits heading ids only in a publication", () => {
    for (const layout of LAYOUTS) {
      const html = published({ ...full, layout });
      for (const anchor of ["dla-kogo", "dla-kogo-nie", "rozwiazanie", "dalej"])
        expect(html).toContain(`id="${anchor}"`);
      expect(html).toContain('<a class="site-prose__link" href="/cennik.pdf">');
    }
  });

  it("shows the author's portrait through the adapter, else initials", () => {
    const withPortrait = {
      ...full,
      layout: "expert_note",
      author: {
        name: "Anna Nowak",
        image: { asset_id: portrait, alt: "Anna Nowak" },
      },
    };
    expect(preview(withPortrait)).toContain(
      `<div class="site-author__portrait"><img src="/media/${portrait}" alt="Anna Nowak" loading="lazy" decoding="async"/></div>`,
    );
    const adapted = renderToStaticMarkup(
      registry.render(
        block(withPortrait),
        "b",
        undefined,
        (image) => `adapter:${image.asset_id}:${Object.keys(image).join(",")}`,
      ),
    );
    expect(adapted).toContain(`adapter:${portrait}:asset_id,alt`);
    // The section photo reaches the adapter without its caption.
    expect(adapted).toContain(`adapter:${photo}:asset_id,alt`);
    expect(adapted).not.toContain("site-author__monogram");
  });

  it("derives no initials from a placeholder or a name without letters", () => {
    for (const name of [
      "[Uzupełnij: imię i nazwisko]",
      "dr [Fill in: name]",
      "— 42",
    ])
      expect(
        preview({ ...full, layout: "expert_note", author: { name } }),
      ).toContain(
        '<span class="site-author__monogram" aria-hidden="true"></span>',
      );
    expect(preview({ ...full, author: { name: "(Łucja) żak" } })).toContain(
      '<span class="site-author__monogram" aria-hidden="true">ŁŻ</span>',
    );
    // core.quote shares the rule and keeps its quotation-mark fallback.
    expect(
      renderToStaticMarkup(
        registry.render(
          {
            block_type: "core.quote",
            schema_version: 1,
            data: {
              layout: "portrait",
              quote: "x",
              author: "[Uzupełnij: autor cytatu]",
            },
          },
          "q",
        ),
      ),
    ).toContain(
      '<span class="site-quote__monogram" aria-hidden="true">“</span>',
    );
  });

  it("escapes hostile text and rejects unsafe actions in the schema", () => {
    const html = published({
      eyebrow: "<script>alert(1)</script>",
      author: { name: '<img src=x onerror="alert(1)">' },
      action: { label: "<b>x</b>", href: "/kontakt/" },
      content: [{ type: "paragraph", content: [{ text: "x" }] }],
    });
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<b>");
    for (const href of [
      "javascript:alert(1)",
      "//evil.example",
      "data:text/html,x",
      "#Bad Anchor",
    ])
      for (const field of ["action", "secondaryAction"])
        expect(() =>
          registry.validate(
            block({
              content: [{ type: "paragraph", content: [{ text: "x" }] }],
              [field]: { label: "x", href },
            }),
          ),
        ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        block({
          layout: "custom-script",
          content: [{ type: "paragraph", content: [{ text: "x" }] }],
        }),
      ),
    ).toThrow(InvalidBlockDataError);
  });
});

describe("richTextChapters", () => {
  it("splits content into an intro and H2 chapters, keeping indexes", () => {
    const content = full.content as unknown as RichTextNode[];
    const { intro, chapters } = richTextChapters(content);
    expect(intro.map((item) => item.index)).toEqual([0]);
    expect(chapters.map((items) => items.map((item) => item.index))).toEqual([
      [1, 2],
      [3, 4, 5],
      [6, 7, 8],
      [9, 10],
    ]);
    expect(chapters.flat().map((item) => item.node)).toEqual(content.slice(1));
    const h3: RichTextNode[] = [
      { type: "heading", level: 3, anchor: "a", text: "a" },
      { type: "paragraph", content: [{ text: "b" }] },
    ];
    expect(richTextChapters(h3)).toEqual({
      intro: [
        { node: h3[0], index: 0 },
        { node: h3[1], index: 1 },
      ],
      chapters: [],
    });
  });
});
