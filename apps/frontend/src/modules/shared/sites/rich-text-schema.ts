/** The WYSIWYG editor's document model is the `core.rich_text` contract, node
 *  for node (ADR-056): what this schema cannot hold, the editor cannot
 *  produce. Headings take no marks, list items hold one paragraph and at most
 *  one sub-list, quotes and notes hold one run of text, figures are atoms. */

import { getSchema, Node, type AnyExtension } from "@tiptap/core";
import { Bold } from "@tiptap/extension-bold";
import { Document } from "@tiptap/extension-document";
import { Heading } from "@tiptap/extension-heading";
import { Italic } from "@tiptap/extension-italic";
import { Link } from "@tiptap/extension-link";
import { BulletList, ListItem, OrderedList } from "@tiptap/extension-list";
import { Paragraph } from "@tiptap/extension-paragraph";
import { Text } from "@tiptap/extension-text";

import type { RichTextNode } from "@saas-core/site-blocks";

import { isRichTextHref } from "./rich-text-markup";

/** A contract field kept on the node. The DOM carries it as `data-*` only so
 *  that copy and paste inside the editor keeps it; it is never published. */
function field(key: string, data = key) {
  return {
    default: null,
    parseHTML: (element: HTMLElement) => element.getAttribute(`data-${data}`),
    renderHTML: (attributes: Record<string, unknown>) =>
      attributes[key] == null ? {} : { [`data-${data}`]: attributes[key] },
  };
}

const RichHeading = Heading.extend({
  content: "text*",
  marks: "",
  addAttributes() {
    return { ...this.parent?.(), anchor: field("anchor") };
  },
}).configure({ levels: [2, 3, 4] });

const RichListItem = ListItem.extend({
  content: "paragraph (bulletList | orderedList)?",
});

const Quote = Node.create({
  name: "quote",
  group: "block",
  content: "text*",
  defining: true,
  addAttributes: () => ({
    author: field("author"),
    source: field("source"),
    href: field("href"),
  }),
  parseHTML: () => [{ tag: "blockquote" }],
  renderHTML: ({ HTMLAttributes }) => ["blockquote", HTMLAttributes, 0],
});

const Note = Node.create({
  name: "note",
  group: "block",
  content: "text*",
  defining: true,
  addAttributes: () => ({ tone: field("tone"), title: field("title") }),
  parseHTML: () => [{ tag: "aside[data-note]" }],
  renderHTML: ({ HTMLAttributes }) => [
    "aside",
    { "data-note": "", ...HTMLAttributes },
    0,
  ],
});

const Figure = Node.create({
  name: "figure",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({
    assetId: field("assetId", "asset-id"),
    alt: field("alt"),
    caption: field("caption"),
    width: field("width"),
  }),
  parseHTML: () => [{ tag: "figure[data-asset-id]" }],
  renderHTML: ({ HTMLAttributes }) => ["figure", HTMLAttributes],
});

export type RichTextNodeType = RichTextNode["type"];

/** `allowed` narrows the blocks, as the aside does (paragraphs and lists):
 *  pasted headings then arrive as paragraphs. */
export function richTextExtensions(
  allowed?: readonly RichTextNodeType[],
): AnyExtension[] {
  const has = (type: RichTextNodeType) => !allowed || allowed.includes(type);
  return [
    Document,
    Paragraph,
    Text,
    Bold,
    Italic,
    Link.configure({
      autolink: false,
      linkOnPaste: false,
      openOnClick: false,
      HTMLAttributes: { rel: null, target: null, class: null },
      isAllowedUri: (url) => isRichTextHref(url),
    }),
    ...(has("heading") ? [RichHeading] : []),
    ...(has("list") ? [BulletList, OrderedList, RichListItem] : []),
    ...(has("quote") ? [Quote] : []),
    ...(has("note") ? [Note] : []),
    ...(has("figure") ? [Figure] : []),
  ];
}

export const richTextSchema = getSchema(richTextExtensions());
