/** `core.rich_text` content ⇄ the WYSIWYG editor's document (ProseMirror JSON
 *  over `rich-text-schema.ts`). The stored JSON is the source of truth: the
 *  editor is loaded from it and every change is written back as it (ADR-056).
 *
 *  The round trip is exact up to the canonical runs of `normalizeSpans`:
 *  neighbouring runs with the same marks merge and runs over the contract
 *  limit split. On the way back, text blocks left empty (a paragraph, heading
 *  or list item still being written) are dropped, while quotes, notes and
 *  figures always stay: they carry fields besides their text. */

import type { JSONContent } from "@tiptap/core";

import {
  richTextAnchorSlug,
  type RichTextListItem,
  type RichTextNode,
  type RichTextSpan,
} from "@saas-core/site-blocks";

import { normalizeSpans } from "./rich-text-markup";

type ListStyle = "bullet" | "ordered";

function textNodes(spans: readonly RichTextSpan[]): JSONContent[] {
  return spans.flatMap((span) => {
    if (!span.text) return [];
    const marks = [
      ...(span.bold ? [{ type: "bold" }] : []),
      ...(span.italic ? [{ type: "italic" }] : []),
      ...(span.href !== undefined
        ? [{ type: "link", attrs: { href: span.href } }]
        : []),
    ];
    return [
      { type: "text", text: span.text, ...(marks.length ? { marks } : {}) },
    ];
  });
}

function list(
  style: ListStyle,
  items: readonly RichTextListItem[],
): JSONContent {
  return {
    type: style === "bullet" ? "bulletList" : "orderedList",
    content: items.map((item) => ({
      type: "listItem",
      content: [
        { type: "paragraph", content: textNodes(item.content) },
        ...(item.children
          ? [list(item.children.style, item.children.items)]
          : []),
      ],
    })),
  };
}

const optional = (value: string | undefined) => value ?? null;

function editorNode(node: RichTextNode): JSONContent {
  switch (node.type) {
    case "paragraph":
      return { type: "paragraph", content: textNodes(node.content) };
    case "heading":
      return {
        type: "heading",
        attrs: { level: node.level, anchor: node.anchor },
        content: node.text ? [{ type: "text", text: node.text }] : [],
      };
    case "list":
      return list(node.style, node.items);
    case "quote":
      return {
        type: "quote",
        attrs: {
          author: optional(node.author),
          source: optional(node.source),
          href: optional(node.href),
        },
        content: textNodes(node.content),
      };
    case "note":
      return {
        type: "note",
        attrs: { tone: optional(node.tone), title: optional(node.title) },
        content: textNodes(node.content),
      };
    case "figure":
      return {
        type: "figure",
        attrs: {
          assetId: node.image.asset_id,
          alt: node.image.alt,
          caption: optional(node.caption),
          width: optional(node.width),
        },
      };
  }
}

export function toEditorDoc(nodes: readonly RichTextNode[]): JSONContent {
  // The editor needs a block to put the caret in; an empty paragraph is
  // dropped again on the way back.
  const content = nodes.map(editorNode);
  return {
    type: "doc",
    content: content.length ? content : [{ type: "paragraph" }],
  };
}

function spans(content: readonly JSONContent[] = []): RichTextSpan[] {
  return normalizeSpans(
    content.flatMap((node) => {
      if (node.type !== "text" || !node.text) return [];
      const span: RichTextSpan = { text: node.text };
      for (const mark of node.marks ?? []) {
        if (mark.type === "bold") span.bold = true;
        else if (mark.type === "italic") span.italic = true;
        else if (mark.type === "link" && typeof mark.attrs?.href === "string")
          span.href = mark.attrs.href;
      }
      return [span];
    }),
  );
}

const styleOf = (node: JSONContent): ListStyle | undefined =>
  node.type === "bulletList"
    ? "bullet"
    : node.type === "orderedList"
      ? "ordered"
      : undefined;

/** Every paragraph under a list item, depth first: a sub-list deeper than the
 *  contract allows is flattened into its parent's sub-list, never lost. */
function itemTexts(item: JSONContent): RichTextSpan[][] {
  return (item.content ?? []).flatMap((child) =>
    child.type === "paragraph"
      ? [spans(child.content)]
      : (child.content ?? []).flatMap(itemTexts),
  );
}

function listNode(node: JSONContent, style: ListStyle): RichTextNode | null {
  const items = (node.content ?? []).flatMap((item): RichTextListItem[] => {
    const [first, ...rest] = item.content ?? [];
    const content = first?.type === "paragraph" ? spans(first.content) : [];
    const sub = rest.find((child) => styleOf(child));
    const subItems = (sub?.content ?? [])
      .flatMap(itemTexts)
      .filter((texts) => texts.length)
      .map((texts) => ({ content: texts }));
    if (!content.length && !subItems.length) return [];
    return [
      {
        content,
        ...(sub && subItems.length
          ? { children: { style: styleOf(sub)!, items: subItems } }
          : {}),
      },
    ];
  });
  return items.length ? { type: "list", style, items } : null;
}

const present = <K extends string>(key: K, value: unknown) =>
  typeof value === "string" ? ({ [key]: value } as Record<K, string>) : {};

export function fromEditorDoc(doc: JSONContent): RichTextNode[] {
  const taken = new Set<string>();
  return (doc.content ?? []).flatMap((node): RichTextNode[] => {
    const attrs = node.attrs ?? {};
    switch (node.type) {
      case "paragraph": {
        const content = spans(node.content);
        return content.length ? [{ type: "paragraph", content }] : [];
      }
      case "heading": {
        const text = (node.content ?? [])
          .map((part) => part.text ?? "")
          .join("");
        if (!text) return [];
        const anchor =
          typeof attrs.anchor === "string" && attrs.anchor
            ? attrs.anchor
            : richTextAnchorSlug(text, taken);
        taken.add(anchor);
        return [{ type: "heading", level: attrs.level, anchor, text }];
      }
      case "bulletList":
      case "orderedList": {
        const result = listNode(node, styleOf(node)!);
        return result ? [result] : [];
      }
      case "quote":
        return [
          {
            type: "quote",
            content: spans(node.content),
            ...present("author", attrs.author),
            ...present("source", attrs.source),
            ...present("href", attrs.href),
          },
        ];
      case "note":
        return [
          {
            type: "note",
            ...(typeof attrs.tone === "string"
              ? { tone: attrs.tone as "info" | "tip" | "warning" }
              : {}),
            ...present("title", attrs.title),
            content: spans(node.content),
          },
        ];
      case "figure":
        return [
          {
            type: "figure",
            image: {
              asset_id: String(attrs.assetId ?? ""),
              alt: String(attrs.alt ?? ""),
            },
            ...present("caption", attrs.caption),
            ...(attrs.width === "column" || attrs.width === "wide"
              ? { width: attrs.width }
              : {}),
          },
        ];
      default:
        return [];
    }
  });
}
