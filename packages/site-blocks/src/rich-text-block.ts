import { Fragment, createElement as h, type ReactNode } from "react";

import { plainBlockText } from "./block-text";

import type {
  BlockComponentProps,
  BlockEditor,
  BlockImageRenderer,
  BlockTextRenderer,
  JsonObject,
  RichTextNode,
  RichTextSpan,
  RichTextV1Data,
  RichTextV2Data,
} from "./types";

/** v1 text becomes one paragraph with one run; not a single character moves. */
export function migrateRichTextV1ToV2(data: Readonly<JsonObject>): JsonObject {
  const legacy = data as RichTextV1Data;
  return { content: [{ type: "paragraph", content: [{ text: legacy.text }] }] };
}

interface Context {
  readonly text: BlockTextRenderer;
  readonly editor?: BlockEditor;
  readonly imageRenderer?: BlockImageRenderer;
  /** Heading ids only in a publication: several previews on one panel screen
   *  would otherwise repeat the same id. */
  readonly publication: boolean;
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
        { key, className: "site-quote" },
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

function nodes(
  content: readonly RichTextNode[],
  path: readonly string[],
  context: Context,
): ReactNode[] {
  return content.map((node, index) =>
    richTextNode(node, [...path, String(index)], context, index),
  );
}

/** A v2 block that is still exactly a v1 text renders v1's markup, byte for
 *  byte: publications always render through the newest component, and the
 *  migration alone must not redesign a published page. */
function legacySpan(data: RichTextV2Data): RichTextSpan | null {
  if (
    data.layout !== undefined ||
    data.title !== undefined ||
    data.lead !== undefined ||
    data.aside !== undefined ||
    data.content.length !== 1
  )
    return null;
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
  const richText = data as RichTextV2Data;
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
  const context: Context = {
    text,
    editor,
    imageRenderer,
    publication: options?.preview === false,
  };
  const layout = richText.layout ?? "column";
  // Built from plain strings: the index repeats headings the reader edits in
  // place below, and one data path must map to one rendered text.
  const chapters =
    layout === "chapters"
      ? richText.content.flatMap((node) =>
          node.type === "heading" && node.level === 2 ? [node] : [],
        )
      : [];
  return h(
    "section",
    {
      className: `site-block site-section site-section--rich_text site-section--${layout}`,
      "data-block-type": "core.rich_text",
      "data-section-layout": layout,
    },
    richText.title !== undefined || richText.lead !== undefined
      ? h(
          "div",
          { className: "site-section__intro" },
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
      : null,
    chapters.length > 0
      ? h(
          "nav",
          {
            className: "site-section__toc",
            "aria-label": options?.locale === "en" ? "Contents" : "Spis treści",
          },
          h(
            "ol",
            null,
            chapters.map((heading, index) =>
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
      : null,
    h(
      "div",
      { className: "site-prose" },
      nodes(richText.content, ["content"], context),
    ),
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
      : null,
  );
}
