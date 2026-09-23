import { Fragment, createElement as h, type ReactNode } from "react";

import { plainBlockText } from "./block-text";
import { monogram, picture } from "./editorial-blocks";

import type {
  BlockComponentProps,
  BlockEditor,
  BlockImageRenderer,
  BlockTextRenderer,
  JsonObject,
  RichTextNode,
  RichTextSpan,
  RichTextV1Data,
  RichTextV3Data,
} from "./types";

/** v1 text becomes one paragraph with one run; not a single character moves. */
export function migrateRichTextV1ToV2(data: Readonly<JsonObject>): JsonObject {
  const legacy = data as RichTextV1Data;
  return { content: [{ type: "paragraph", content: [{ text: legacy.text }] }] };
}

/** v3 only adds optional fields, so v2 data is already valid v3 data. */
export function migrateRichTextV2ToV3(data: Readonly<JsonObject>): JsonObject {
  return { ...data };
}

interface Context {
  readonly text: BlockTextRenderer;
  readonly editor?: BlockEditor;
  readonly imageRenderer?: BlockImageRenderer;
  /** Heading ids only in a publication: several previews on one panel screen
   *  would otherwise repeat the same id. */
  readonly publication: boolean;
  /** margin_quote: the one quote node CSS lifts into the margin. It renders
   *  once, in reading position; the layout only moves it. */
  readonly marginQuote?: RichTextNode;
}

function externalRel(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

/** Nesting is fixed (a > strong > em), so two runs with the same marks always
 *  produce the same markup. Links are spans in the editor, like other blocks. */
function spans(
  content: readonly RichTextSpan[],
  path: readonly string[],
  context: Context,
): ReactNode[] {
  return content.map((span, index) => {
    let node: ReactNode = context.text(
      [...path, String(index), "text"],
      span.text,
    );
    if (span.italic) node = h("em", null, node);
    if (span.bold) node = h("strong", null, node);
    if (span.href !== undefined)
      node = h(
        context.editor ? "span" : "a",
        {
          className: "site-prose__link",
          href: context.editor ? undefined : span.href,
          rel: context.editor ? undefined : externalRel(span.href),
        },
        node,
      );
    return h(Fragment, { key: index }, node);
  });
}

function list(
  node: Extract<RichTextNode, { type: "list" }>,
  path: readonly string[],
  context: Context,
  key: number,
) {
  return h(
    node.style === "ordered" ? "ol" : "ul",
    { key },
    node.items.map((item, k) =>
      h(
        "li",
        { key: k },
        spans(item.content, [...path, "items", String(k), "content"], context),
        item.children
          ? h(
              item.children.style === "ordered" ? "ol" : "ul",
              null,
              item.children.items.map((child, m) =>
                h(
                  "li",
                  { key: m },
                  spans(
                    child.content,
                    [
                      ...path,
                      "items",
                      String(k),
                      "children",
                      "items",
                      String(m),
                      "content",
                    ],
                    context,
                  ),
                ),
              ),
            )
          : null,
      ),
    ),
  );
}

function richTextNode(
  node: RichTextNode,
  path: readonly string[],
  context: Context,
  key: number,
): ReactNode {
  const { text, editor } = context;
  switch (node.type) {
    case "paragraph":
      return h(
        "p",
        { key },
        spans(node.content, [...path, "content"], context),
      );
    case "heading":
      return h(
        `h${node.level}`,
        {
          key,
          id: context.publication ? node.anchor : undefined,
          role: editor ? "presentation" : undefined,
        },
        text([...path, "text"], node.text),
      );
    case "list":
      return list(node, path, context, key);
    case "quote": {
      const source =
        node.source === undefined
          ? null
          : h(
              "cite",
              null,
              node.href !== undefined && !editor
                ? h(
                    "a",
                    { href: node.href, rel: externalRel(node.href) },
                    text([...path, "source"], node.source),
                  )
                : text([...path, "source"], node.source),
            );
      return h(
        "figure",
        {
          key,
          className:
            node === context.marginQuote
              ? "site-quote site-quote--margin"
              : "site-quote",
        },
        h(
          "blockquote",
          null,
          h("p", null, spans(node.content, [...path, "content"], context)),
        ),
        node.author !== undefined || source
          ? h(
              "figcaption",
              null,
              node.author === undefined
                ? null
                : text([...path, "author"], node.author),
              node.author !== undefined && source ? ", " : null,
              source,
            )
          : null,
      );
    }
    case "note":
      return h(
        "div",
        {
          key,
          className: `site-note site-note--${node.tone ?? "info"}`,
          role: "note",
        },
        node.title === undefined
          ? null
          : h(
              "strong",
              { className: "site-note__title" },
              text([...path, "title"], node.title),
            ),
        h("p", null, spans(node.content, [...path, "content"], context)),
      );
    case "figure":
      return h(
        "figure",
        {
          key,
          className: `site-figure site-figure--${node.width ?? "column"}`,
        },
        context.imageRenderer
          ? context.imageRenderer(node.image)
          : h("img", {
              src: `/media/${node.image.asset_id}`,
              alt: node.image.alt,
              loading: "lazy",
              decoding: "async",
            }),
        node.caption === undefined
          ? null
          : h("figcaption", null, text([...path, "caption"], node.caption)),
      );
  }
}

/** A content node with its index, which the editor's data path needs. */
export interface PlacedNode {
  readonly node: RichTextNode;
  readonly index: number;
}

/** Content before the first H2 is the intro; each H2 opens a chapter that
 *  runs to the next H2. Layouts arrange chapters, never reorder them. */
export function richTextChapters(content: readonly RichTextNode[]): {
  intro: PlacedNode[];
  chapters: PlacedNode[][];
} {
  const intro: PlacedNode[] = [];
  const chapters: PlacedNode[][] = [];
  content.forEach((node, index) => {
    if (node.type === "heading" && node.level === 2)
      chapters.push([{ node, index }]);
    else (chapters.at(-1) ?? intro).push({ node, index });
  });
  return { intro, chapters };
}

function placed(items: readonly PlacedNode[], context: Context): ReactNode[] {
  return items.map(({ node, index }) =>
    richTextNode(node, ["content", String(index)], context, index),
  );
}

function prose(items: readonly PlacedNode[], context: Context): ReactNode {
  return items.length > 0
    ? h("div", { className: "site-prose" }, placed(items, context))
    : null;
}

function nodes(
  content: readonly RichTextNode[],
  path: readonly string[],
  context: Context,
): ReactNode[] {
  return content.map((node, index) =>
    richTextNode(node, [...path, String(index)], context, index),
  );
}

/** A wrapper only when something is inside it. */
function wrap(className: string, ...children: ReactNode[]): ReactNode {
  return children.some((child) => child !== null)
    ? h("div", { className }, ...children)
    : null;
}

/** A v2 block that is still exactly a v1 text renders v1's markup, byte for
 *  byte: publications always render through the newest component, and the
 *  migration alone must not redesign a published page. Any other field —
 *  v2's or v3's — leaves the legacy shape. */
function legacySpan(data: RichTextV3Data): RichTextSpan | null {
  if (Object.keys(data).length !== 1 || data.content.length !== 1) return null;
  const [node] = data.content;
  if (node?.type !== "paragraph" || node.content.length !== 1) return null;
  const [span] = node.content;
  return span !== undefined && Object.keys(span).length === 1 ? span : null;
}

export function RichTextBlock({
  data,
  editor,
  imageRenderer,
  options,
}: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const richText = data as RichTextV3Data;
  const legacy = legacySpan(richText);
  if (legacy)
    return h(
      "section",
      {
        className: "site-block site-block--rich-text",
        "data-block-type": "core.rich_text",
      },
      h("p", null, text(["content", "0", "content", "0", "text"], legacy.text)),
    );
  const layout = richText.layout ?? "column";
  const content = richText.content;
  const context: Context = {
    text,
    editor,
    imageRenderer,
    publication: options?.preview === false,
    marginQuote:
      layout === "margin_quote"
        ? content.find((node) => node.type === "quote")
        : undefined,
  };
  const all = content.map((node, index) => ({ node, index }));

  // Pieces are built where they are placed, so the editor adapter sees the
  // texts in DOM order.
  const intro = (): ReactNode =>
    richText.eyebrow !== undefined ||
    richText.title !== undefined ||
    richText.lead !== undefined
      ? h(
          "div",
          { className: "site-section__intro" },
          richText.eyebrow === undefined
            ? null
            : h(
                "p",
                { className: "site-section__eyebrow" },
                text(["eyebrow"], richText.eyebrow),
              ),
          richText.title === undefined
            ? null
            : h(
                "h2",
                editor ? { role: "presentation" } : null,
                text(["title"], richText.title),
              ),
          richText.lead === undefined
            ? null
            : h(
                "p",
                { className: "site-section__lead" },
                text(["lead"], richText.lead),
              ),
        )
      : null;
  // Built from plain strings: the index repeats headings the reader edits in
  // place below, and one data path must map to one rendered text.
  const tocHeadings =
    layout === "chapters"
      ? content.flatMap((node) =>
          node.type === "heading" && node.level === 2 ? [node] : [],
        )
      : [];
  const toc = (): ReactNode =>
    tocHeadings.length > 0
      ? h(
          "nav",
          {
            className: "site-section__toc",
            "aria-label": options?.locale === "en" ? "Contents" : "Spis treści",
          },
          h(
            "ol",
            null,
            tocHeadings.map((heading, index) =>
              h(
                "li",
                { key: index },
                editor
                  ? h("span", null, heading.text)
                  : h("a", { href: `#${heading.anchor}` }, heading.text),
              ),
            ),
          ),
        )
      : null;
  const image = (): ReactNode =>
    richText.image
      ? h(
          "figure",
          { key: "image", className: "site-section__image" },
          picture(
            { asset_id: richText.image.asset_id, alt: richText.image.alt },
            imageRenderer,
          ),
          richText.image.caption === undefined
            ? null
            : h(
                "figcaption",
                null,
                text(["image", "caption"], richText.image.caption),
              ),
        )
      : null;
  const author = (): ReactNode =>
    richText.author
      ? h(
          "div",
          { className: "site-author" },
          richText.author.image
            ? h(
                "div",
                { className: "site-author__portrait" },
                picture(richText.author.image, imageRenderer),
              )
            : h(
                "span",
                { className: "site-author__monogram", "aria-hidden": true },
                // Empty for a placeholder name: CSS draws a neutral figure.
                monogram(richText.author.name, ""),
              ),
          h(
            "div",
            { className: "site-author__text" },
            h(
              "p",
              { className: "site-author__name" },
              text(["author", "name"], richText.author.name),
            ),
            richText.author.role === undefined
              ? null
              : h(
                  "p",
                  { className: "site-author__role" },
                  text(["author", "role"], richText.author.role),
                ),
          ),
        )
      : null;
  const aside = (): ReactNode =>
    richText.aside
      ? h(
          "aside",
          { className: "site-section__aside" },
          richText.aside.title === undefined
            ? null
            : h(
                "h3",
                editor ? { role: "presentation" } : null,
                text(["aside", "title"], richText.aside.title),
              ),
          nodes(richText.aside.content, ["aside", "content"], context),
        )
      : null;
  // One primary action per section; in the editor both are editable text
  // without navigation, like every other block's action.
  const action = (
    value: { label: string; href: string } | undefined,
    field: "action" | "secondaryAction",
    className: string,
  ) =>
    value === undefined
      ? null
      : h(
          editor ? "span" : "a",
          {
            className,
            href: editor ? undefined : value.href,
            rel: editor ? undefined : externalRel(value.href),
          },
          text([field, "label"], value.label),
        );
  const actions = (): ReactNode =>
    wrap(
      "site-section__actions",
      action(richText.action, "action", "site-section__action"),
      action(
        richText.secondaryAction,
        "secondaryAction",
        "site-section__action site-section__action--secondary",
      ),
    );

  const { intro: opening, chapters } = richTextChapters(content);
  const chapter = (
    items: readonly PlacedNode[],
    key: number,
    tag = "div",
    extra?: () => ReactNode,
  ) =>
    h(
      tag,
      { key, className: "site-chapter" },
      layout === "numbered_sections"
        ? h(
            "span",
            { className: "site-chapter__number", "aria-hidden": true },
            String(key + 1).padStart(2, "0"),
          )
        : null,
      prose(items, context),
      extra?.(),
    );

  let children: ReactNode[];
  switch (layout) {
    case "panorama":
      children = [
        image(),
        intro(),
        prose(all, context),
        author(),
        aside(),
        actions(),
      ];
      break;
    case "summary_box":
      children = [
        intro(),
        aside(),
        prose(all, context),
        image(),
        author(),
        actions(),
      ];
      break;
    case "manifesto":
      children = [
        intro(),
        prose(all, context),
        actions(),
        image(),
        author(),
        aside(),
      ];
      break;
    case "illustrated": {
      // The photo stands in the reading flow after the first paragraph.
      const first = content.findIndex((node) => node.type === "paragraph");
      const split = first === -1 ? all.length : first + 1;
      children = [
        intro(),
        h(
          "div",
          { className: "site-prose" },
          placed(all.slice(0, split), context),
          image(),
          placed(all.slice(split), context),
        ),
        author(),
        aside(),
        actions(),
      ];
      break;
    }
    case "side_photo":
      children = [
        intro(),
        image(),
        wrap(
          "site-section__main",
          prose(all, context),
          author(),
          aside(),
          actions(),
        ),
      ];
      break;
    case "expert_note":
      children = [
        intro(),
        wrap("site-section__expert", author(), actions()),
        wrap("site-section__main", prose(all, context), image(), aside()),
      ];
      break;
    case "two_parts":
      children = [
        intro(),
        prose(opening, context),
        chapters.length > 0
          ? h(
              "div",
              { className: "site-section__parts" },
              chapters.slice(0, 2).map((items, key) => chapter(items, key)),
            )
          : null,
        prose(chapters.slice(2).flat(), context),
        image(),
        author(),
        aside(),
        actions(),
      ];
      break;
    case "alternating_chapters":
      children = [
        intro(),
        prose(opening, context),
        chapters.length > 0
          ? h(
              "div",
              { className: "site-chapters" },
              chapters.map((items, key) => {
                // The chapter's illustrations join its heading's side.
                const [heading, ...rest] = items;
                const figures = rest.filter(
                  (item) => item.node.type === "figure",
                );
                return h(
                  "div",
                  { key, className: "site-chapter" },
                  h(
                    "div",
                    { className: "site-chapter__head" },
                    placed([heading!, ...figures], context),
                  ),
                  prose(
                    rest.filter((item) => item.node.type !== "figure"),
                    context,
                  ),
                );
              }),
            )
          : null,
        image(),
        author(),
        aside(),
        actions(),
      ];
      break;
    case "timeline":
    case "numbered_sections":
      children = [
        intro(),
        prose(opening, context),
        chapters.length > 0
          ? h(
              "ol",
              { className: "site-chapters" },
              chapters.map((items, key) => chapter(items, key, "li")),
            )
          : null,
        image(),
        author(),
        aside(),
        actions(),
      ];
      break;
    case "problem_solution": {
      // Problem → analysis → solution; the action closes the solution panel.
      const panels = chapters.slice(0, 3);
      children = [
        intro(),
        prose(opening, context),
        panels.length > 0
          ? h(
              "div",
              { className: "site-chapters" },
              panels.map((items, key) =>
                chapter(
                  items,
                  key,
                  "div",
                  key === panels.length - 1 ? actions : undefined,
                ),
              ),
            )
          : null,
        prose(chapters.slice(3).flat(), context),
        image(),
        author(),
        aside(),
        panels.length > 0 ? null : actions(),
      ];
      break;
    }
    default:
      // column, split_intro, facts_panel, chapters, lead_statement,
      // margin_quote, howto, resources and essay_cta keep the reading order
      // and differ in CSS. v3 fields follow the text; the actions end it.
      children = [
        intro(),
        toc(),
        prose(all, context),
        image(),
        author(),
        aside(),
        actions(),
      ];
  }
  return h(
    "section",
    {
      className: `site-block site-section site-section--rich_text site-section--${layout}`,
      "data-block-type": "core.rich_text",
      "data-section-layout": layout,
    },
    ...children,
  );
}
