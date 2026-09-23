/** Clipboard → rich-text nodes. Only the allowlist of the v2 contract comes
 *  through: paragraphs, headings, two-level lists, quotes, bold, italic and
 *  links with an allowed address. Styles, classes, images and scripts never
 *  do — the result is JSON runs, not HTML. Word and Google Docs wrap their
 *  markup in presentational elements, so marks also come from inline
 *  `font-weight`/`font-style`, and wrappers holding blocks are walked through. */

import {
  richTextAnchorSlug,
  type RichTextListItem,
  type RichTextNode,
  type RichTextSpan,
} from "@saas-core/site-blocks";

import { isRichTextHref, normalizeSpans } from "./rich-text-markup";

const MAX_NODES = 160;
const MAX_HEADING = 200;
const BLOCK_SELECTOR =
  "p,div,h1,h2,h3,h4,h5,h6,ul,ol,li,blockquote,table,tr,section,article,header,footer,main,aside,nav,figure,figcaption,pre,address,dl,dt,dd,hr";
const DROPPED = new Set([
  "SCRIPT",
  "STYLE",
  "TEMPLATE",
  "NOSCRIPT",
  "IFRAME",
  "OBJECT",
  "EMBED",
  "CANVAS",
  "VIDEO",
  "AUDIO",
  "IMG",
  "PICTURE",
  "SVG",
  "HEAD",
  "TITLE",
  "META",
  "LINK",
]);
const IMAGES = new Set(["IMG", "PICTURE", "SVG"]);

type Marks = { bold: boolean; italic: boolean; href?: string };
type Paragraph = Extract<RichTextNode, { type: "paragraph" }>;

/** HTML whitespace collapses; a non-breaking space is content. */
const collapse = (text: string) => text.replace(/[ \t\n\r\f]+/g, " ");

/** Runs ready to store: collapsed across run boundaries, trimmed at the ends
 *  of the block, canonical. Whitespace-only blocks come back empty. */
function finish(spans: RichTextSpan[]): RichTextSpan[] {
  const out: RichTextSpan[] = [];
  let spaceBefore = true;
  for (const run of spans) {
    const text: string = spaceBefore ? run.text.replace(/^ /, "") : run.text;
    if (!text) continue;
    out.push({ ...run, text });
    spaceBefore = text.endsWith(" ");
  }
  const last = out[out.length - 1];
  if (last) last.text = last.text.replace(/ $/, "");
  const result = normalizeSpans(out);
  return result.every((run) => /^\s*$/.test(run.text)) ? [] : result;
}

function marksOf(element: Element, marks: Marks): Marks {
  const style = (element.getAttribute("style") ?? "").toLowerCase();
  const weight = /font-weight\s*:\s*([a-z0-9]+)/.exec(style)?.[1];
  const fontStyle = /font-style\s*:\s*([a-z]+)/.exec(style)?.[1];
  const tag = element.tagName;
  const bold =
    weight !== undefined
      ? weight === "bold" || weight === "bolder" || Number(weight) >= 600
      : tag === "B" || tag === "STRONG" || marks.bold;
  const italic =
    fontStyle !== undefined
      ? fontStyle === "italic" || fontStyle === "oblique"
      : tag === "I" || tag === "EM" || marks.italic;
  const rawHref =
    tag === "A" ? element.getAttribute("href")?.trim() : undefined;
  const href =
    rawHref !== undefined
      ? isRichTextHref(rawHref)
        ? rawHref
        : undefined
      : marks.href;
  return { bold, italic, href };
}

/** Word marks its list bullets with `mso-list:Ignore`; they are not text. */
const isWordListMarker = (element: Element) =>
  /mso-list\s*:\s*ignore/i.test(element.getAttribute("style") ?? "");

export function htmlToRichNodes(
  html: string,
  takenAnchors: ReadonlySet<string> = new Set(),
): { nodes: RichTextNode[]; droppedImages: boolean } {
  const body = new DOMParser().parseFromString(html, "text/html").body;
  const taken = new Set(takenAnchors);
  const nodes: RichTextNode[] = [];
  let droppedImages = false;
  let pending: RichTextSpan[] = [];
  // Word writes list items as paragraphs of class MsoListParagraph*.
  let wordList: Extract<RichTextNode, { type: "list" }> | undefined;

  const inline = (node: Node, marks: Marks, out: RichTextSpan[]): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = collapse(node.textContent ?? "");
      if (text) out.push({ text, ...runMarks(marks) });
      return;
    }
    if (!(node instanceof Element)) return;
    if (IMAGES.has(node.tagName.toUpperCase())) droppedImages = true;
    if (DROPPED.has(node.tagName.toUpperCase()) || isWordListMarker(node))
      return;
    if (node.tagName === "BR") {
      out.push({ text: " ", ...runMarks(marks) });
      return;
    }
    const nested = marksOf(node, marks);
    // Block children inside a quote or a cell read as one line of text.
    const block = node.matches(BLOCK_SELECTOR);
    if (block) out.push({ text: " " });
    node.childNodes.forEach((child) => inline(child, nested, out));
    if (block) out.push({ text: " " });
  };

  const flush = () => {
    const content = finish(pending);
    pending = [];
    if (content.length > 0) nodes.push({ type: "paragraph", content });
  };

  const push = (node: RichTextNode) => {
    flush();
    if (node.type !== "list" || node !== wordList) wordList = undefined;
    nodes.push(node);
  };

  const listItems = (list: Element): RichTextListItem[] => {
    const items: RichTextListItem[] = [];
    for (const li of list.children) {
      // Google Docs nests a sub-list beside the items, not inside one.
      if (/^(UL|OL)$/.test(li.tagName)) {
        const parent = items[items.length - 1];
        const nested = flatItems(li).map((content) => ({ content }));
        if (!parent) items.push(...nested);
        else if (nested.length > 0) {
          parent.children ??= {
            style: li.tagName === "OL" ? "ordered" : "bullet",
            items: [],
          };
          parent.children.items.push(...nested);
        }
        continue;
      }
      if (li.tagName !== "LI") continue;
      const content: RichTextSpan[] = [];
      const nestedLists: Element[] = [];
      li.childNodes.forEach((child) => {
        if (child instanceof Element && /^(UL|OL)$/.test(child.tagName))
          nestedLists.push(child);
        else inline(child, { bold: false, italic: false }, content);
      });
      const children = nestedLists.flatMap((nested) =>
        flatItems(nested).map((childContent) => ({ content: childContent })),
      );
      const finished = finish(content);
      if (finished.length === 0 && children.length === 0) continue;
      items.push({
        content: finished.length > 0 ? finished : [{ text: "–" }],
        ...(children.length > 0
          ? {
              children: {
                style: nestedLists[0].tagName === "OL" ? "ordered" : "bullet",
                items: children,
              },
            }
          : {}),
      });
    }
    return items;
  };

  /** Every item of a nested list, any depth, as one flat level. */
  const flatItems = (list: Element): RichTextSpan[][] =>
    [...list.children].flatMap((li) => {
      if (/^(UL|OL)$/.test(li.tagName)) return flatItems(li);
      if (li.tagName !== "LI") return [];
      const content: RichTextSpan[] = [];
      const deeper: Element[] = [];
      li.childNodes.forEach((child) => {
        if (child instanceof Element && /^(UL|OL)$/.test(child.tagName))
          deeper.push(child);
        else inline(child, { bold: false, italic: false }, content);
      });
      const own = finish(content);
      return [...(own.length > 0 ? [own] : []), ...deeper.flatMap(flatItems)];
    });

  const block = (node: Node): void => {
    if (!(node instanceof Element)) {
      inline(node, { bold: false, italic: false }, pending);
      return;
    }
    const tag = node.tagName.toUpperCase();
    if (IMAGES.has(tag)) droppedImages = true;
    if (DROPPED.has(tag)) return;
    // An inline wrapper (Google Docs' <b id="docs-internal-guid…">) holding
    // blocks is a container, not a mark.
    if (!node.matches(BLOCK_SELECTOR) && !node.querySelector(BLOCK_SELECTOR)) {
      inline(node, { bold: false, italic: false }, pending);
      return;
    }
    const heading = /^H([1-6])$/.exec(tag);
    if (heading) {
      const text = finish(
        (() => {
          const out: RichTextSpan[] = [];
          inline(node, { bold: false, italic: false }, out);
          return out;
        })(),
      )
        .map((run) => run.text)
        .join("");
      if (!text) return;
      if (text.length > MAX_HEADING) {
        // Too long for a heading: keep the words as a paragraph.
        push({ type: "paragraph", content: normalizeSpans([{ text }]) });
        return;
      }
      const level = Number(heading[1]);
      const anchor = richTextAnchorSlug(text, taken);
      taken.add(anchor);
      push({
        type: "heading",
        level: level <= 2 ? 2 : level === 3 ? 3 : 4,
        anchor,
        text,
      });
      return;
    }
    if (tag === "UL" || tag === "OL") {
      const items = listItems(node);
      if (items.length > 0)
        push({
          type: "list",
          style: tag === "OL" ? "ordered" : "bullet",
          items,
        });
      return;
    }
    if (tag === "BLOCKQUOTE") {
      const out: RichTextSpan[] = [];
      node.childNodes.forEach((child) =>
        inline(child, { bold: false, italic: false }, out),
      );
      const content = finish(out);
      if (content.length > 0) push({ type: "quote", content });
      return;
    }
    if (tag === "TABLE") {
      for (const row of node.querySelectorAll("tr")) {
        const cells = [...row.children].flatMap((cell) => {
          const out: RichTextSpan[] = [];
          inline(cell, { bold: false, italic: false }, out);
          const content = finish(out);
          return content.length > 0 ? [content] : [];
        });
        const content = cells.flatMap((cell, index) =>
          index === 0 ? cell : [{ text: " – " }, ...cell],
        );
        if (content.length > 0)
          push({ type: "paragraph", content: normalizeSpans(content) });
      }
      return;
    }
    if (tag === "P" && /^MsoListParagraph/i.test(node.className)) {
      const marker = node.querySelector("[style*='mso-list']");
      const ordered = /^\s*\d+[.)]/.test(marker?.textContent ?? "");
      const out: RichTextSpan[] = [];
      node.childNodes.forEach((child) =>
        inline(child, { bold: false, italic: false }, out),
      );
      const content = finish(out);
      if (content.length === 0) return;
      // Each list starts with CxSpFirst; a lone item has the bare class.
      if (!wordList || /CxSpFirst$|^MsoListParagraph$/i.test(node.className)) {
        wordList = {
          type: "list",
          style: ordered ? "ordered" : "bullet",
          items: [],
        };
        push(wordList);
      }
      wordList.items.push({ content });
      return;
    }
    if (
      /^(P|LI|DT|DD|FIGCAPTION|PRE|ADDRESS)$/.test(tag) &&
      !node.querySelector(BLOCK_SELECTOR)
    ) {
      flush();
      const out: RichTextSpan[] = [];
      node.childNodes.forEach((child) =>
        inline(child, marksOf(node, { bold: false, italic: false }), out),
      );
      const content = finish(out);
      if (content.length > 0) push({ type: "paragraph", content });
      return;
    }
    // A container (div, section, a block-holding wrapper): its inline text
    // around the blocks becomes paragraphs of its own.
    flush();
    node.childNodes.forEach(block);
    flush();
  };

  body.childNodes.forEach(block);
  flush();
  return { nodes: nodes.slice(0, MAX_NODES), droppedImages };
}

function runMarks(marks: Marks): Omit<RichTextSpan, "text"> {
  return {
    ...(marks.bold ? { bold: true as const } : {}),
    ...(marks.italic ? { italic: true as const } : {}),
    ...(marks.href ? { href: marks.href } : {}),
  };
}

const LIST_LINE = /^([ \t]*)([-*•]|\d+[.)])\s+(.*)$/;

/** Plain text: blank lines separate paragraphs; a run of lines starting with
 *  `- `, `* ` or `1. ` is a list, an indented one a sub-item. Text is taken
 *  literally — stars stay stars. */
export function plainTextToRichNodes(text: string): RichTextNode[] {
  const nodes: RichTextNode[] = [];
  for (const chunk of text.replace(/\r\n?/g, "\n").split(/\n(?:[^\S\n]*\n)+/)) {
    let paragraph: string[] = [];
    let list: Extract<RichTextNode, { type: "list" }> | undefined;
    const flush = () => {
      const joined = paragraph.join("\n").replace(/^\n+|\n+$/g, "");
      paragraph = [];
      if (joined.trim()) nodes.push(plainParagraph(joined));
    };
    for (const line of chunk.split("\n")) {
      const match = LIST_LINE.exec(line);
      if (!match || !match[3].trim()) {
        list = undefined;
        paragraph.push(line);
        continue;
      }
      flush();
      const ordered = /\d/.test(match[2]);
      const content = normalizeSpans([{ text: match[3] }]);
      const parent = list?.items[list.items.length - 1];
      if (list && parent && /^(?: {2,}|\t)/.test(match[1])) {
        parent.children ??= {
          style: ordered ? "ordered" : "bullet",
          items: [],
        };
        parent.children.items.push({ content });
        continue;
      }
      if (!list) {
        list = {
          type: "list",
          style: ordered ? "ordered" : "bullet",
          items: [],
        };
        nodes.push(list);
      }
      list.items.push({ content });
    }
    flush();
  }
  return nodes.slice(0, MAX_NODES);
}

function plainParagraph(text: string): Paragraph {
  return { type: "paragraph", content: normalizeSpans([{ text }]) };
}
