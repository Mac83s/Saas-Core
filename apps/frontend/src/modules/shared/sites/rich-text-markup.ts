/** The text form of structured rich text, used only inside the panel's text
 *  fields. What is stored stays JSON runs (`core.rich_text` v2); this module
 *  turns runs into a short, typeable notation and back:
 *
 *  - `**bold**`, `*italic*`, `***both***`, `[label](href)` with marks allowed
 *    inside the label;
 *  - `\` escapes `\ * [ ] ( )`; any other character after `\` is literal;
 *  - a delimiter without its pair, or a run of four or more stars, is text;
 *  - a link whose address fails the contract pattern keeps only its label.
 *
 *  Star runs toggle marks (`*` italic, `**` bold, `***` both), so the writer
 *  can emit one run per change and the reader never has to guess where a
 *  closing delimiter belongs. Spaces are never trimmed. */

import type {
  RichTextListItem,
  RichTextNode,
  RichTextSpan,
} from "@saas-core/site-blocks";

const HREF_PATTERN =
  /^(?:\/(?!\/)|https:\/\/|mailto:|tel:|#[a-z][a-z0-9-]{0,63}$)/;
const MAX_SPAN_TEXT = 4000;
const ESCAPABLE = new Set(["\\", "*", "[", "]", "(", ")"]);

type Marks = { bold: boolean; italic: boolean };

export function isRichTextHref(href: string): boolean {
  return HREF_PATTERN.test(href);
}

function span(text: string, marks: Marks, href?: string): RichTextSpan {
  return {
    text,
    ...(marks.bold ? { bold: true as const } : {}),
    ...(marks.italic ? { italic: true as const } : {}),
    ...(href !== undefined ? { href } : {}),
  };
}

const sameAttributes = (a: RichTextSpan, b: RichTextSpan) =>
  Boolean(a.bold) === Boolean(b.bold) &&
  Boolean(a.italic) === Boolean(b.italic) &&
  a.href === b.href;

/** The canonical runs: no empty text, no address outside the allowlist,
 *  neighbours with the same attributes merged, text over the contract limit
 *  split into more runs (never dropped). */
export function normalizeSpans(spans: readonly RichTextSpan[]): RichTextSpan[] {
  const merged: RichTextSpan[] = [];
  for (const source of spans) {
    if (!source.text) continue;
    const next = span(
      source.text,
      { bold: source.bold === true, italic: source.italic === true },
      source.href !== undefined && isRichTextHref(source.href)
        ? source.href
        : undefined,
    );
    const last = merged[merged.length - 1];
    if (last && sameAttributes(last, next)) last.text += next.text;
    else merged.push(next);
  }
  return merged.flatMap((run) => {
    if (run.text.length <= MAX_SPAN_TEXT) return [run];
    const parts: RichTextSpan[] = [];
    for (let start = 0; start < run.text.length;) {
      let end = Math.min(start + MAX_SPAN_TEXT, run.text.length);
      // Never cut a surrogate pair in half.
      if (end < run.text.length && /[\uD800-\uDBFF]/.test(run.text[end - 1]))
        end -= 1;
      parts.push({ ...run, text: run.text.slice(start, end) });
      start = end;
    }
    return parts;
  });
}

const escapeText = (text: string) => text.replace(/[\\*[\]()]/g, "\\$&");
const escapeHref = (href: string) => href.replace(/[\\()]/g, "\\$&");

function toggle(from: Marks, to: Marks): string {
  const bold = from.bold !== to.bold;
  const italic = from.italic !== to.italic;
  return bold && italic ? "***" : bold ? "**" : italic ? "*" : "";
}

const marksOf = (run: RichTextSpan): Marks => ({
  bold: run.bold === true,
  italic: run.italic === true,
});

export function spansToMarkup(spans: readonly RichTextSpan[]): string {
  const runs = normalizeSpans(spans);
  const plain: Marks = { bold: false, italic: false };
  let state = plain;
  let out = "";
  for (let index = 0; index < runs.length;) {
    const href = runs[index].href;
    if (href === undefined) {
      out += toggle(state, marksOf(runs[index])) + escapeText(runs[index].text);
      state = marksOf(runs[index]);
      index += 1;
      continue;
    }
    // A link label starts in the surrounding marks and returns to them before
    // `]`, so the marks outside the link read the same with or without it.
    let inner = state;
    let label = "";
    for (; index < runs.length && runs[index].href === href; index += 1) {
      label +=
        toggle(inner, marksOf(runs[index])) + escapeText(runs[index].text);
      inner = marksOf(runs[index]);
    }
    out += `[${label}${toggle(inner, state)}](${escapeHref(href)})`;
  }
  return out + toggle(state, plain);
}

/** A link in the notation, for the panel's link button. */
export function linkMarkup(labelMarkup: string, href: string): string {
  return `[${labelMarkup || escapeText(href)}](${escapeHref(href)})`;
}

type Token =
  | { kind: "text"; text: string }
  | { kind: "run"; bold: boolean; italic: boolean; literal: string }
  | { kind: "link"; label: Token[]; href?: string };

/** Index just past the first unescaped `closer` at or after `from`, or -1. */
function findUnescaped(source: string, closer: string, from: number): number {
  for (let index = from; index < source.length; index += 1) {
    if (source[index] === "\\" && ESCAPABLE.has(source[index + 1] ?? ""))
      index += 1;
    else if (source[index] === closer) return index;
  }
  return -1;
}

const unescape = (text: string) => text.replace(/\\([\\*[\]()])/g, "$1");

function tokenize(source: string, links: boolean): Token[] {
  const tokens: Token[] = [];
  const text = (value: string) => {
    const last = tokens[tokens.length - 1];
    if (last?.kind === "text") last.text += value;
    else tokens.push({ kind: "text", text: value });
  };
  for (let index = 0; index < source.length;) {
    const char = source[index];
    if (char === "\\" && ESCAPABLE.has(source[index + 1] ?? "")) {
      text(source[index + 1]);
      index += 2;
    } else if (char === "*") {
      let end = index;
      while (source[end] === "*") end += 1;
      const length = end - index;
      if (length > 3) text(source.slice(index, end));
      else
        tokens.push({
          kind: "run",
          bold: length >= 2,
          italic: length !== 2,
          literal: "",
        });
      index = end;
    } else if (char === "[" && links) {
      const close = findUnescaped(source, "]", index + 1);
      const hrefEnd =
        close >= 0 && source[close + 1] === "("
          ? findUnescaped(source, ")", close + 2)
          : -1;
      if (hrefEnd < 0) {
        text(char);
        index += 1;
        continue;
      }
      const href = unescape(source.slice(close + 2, hrefEnd));
      tokens.push({
        kind: "link",
        label: tokenize(source.slice(index + 1, close), false),
        href: isRichTextHref(href) ? href : undefined,
      });
      index = hrefEnd + 1;
    } else {
      text(char);
      index += 1;
    }
  }
  // A mark toggled an odd number of times in this scope has no partner: its
  // last delimiter is text again.
  for (const mark of ["bold", "italic"] as const) {
    const runs = tokens.filter(
      (token): token is Extract<Token, { kind: "run" }> =>
        token.kind === "run" && token[mark],
    );
    const last = runs[runs.length - 1];
    if (runs.length % 2 === 1 && last) {
      last[mark] = false;
      last.literal += mark === "bold" ? "**" : "*";
    }
  }
  return tokens;
}

function emit(
  tokens: readonly Token[],
  start: Marks,
  href: string | undefined,
  out: RichTextSpan[],
): void {
  let state = start;
  for (const token of tokens) {
    if (token.kind === "text") out.push(span(token.text, state, href));
    else if (token.kind === "link") emit(token.label, state, token.href, out);
    else {
      if (token.literal) out.push(span(token.literal, state, href));
      state = {
        bold: state.bold !== token.bold,
        italic: state.italic !== token.italic,
      };
    }
  }
}

export function markupToSpans(markup: string): RichTextSpan[] {
  const out: RichTextSpan[] = [];
  emit(tokenize(markup, true), { bold: false, italic: false }, undefined, out);
  return normalizeSpans(out);
}

const CHILD_LINE = /^(?: {2,}|\t)/;
const ORDERED_MARKER = /^\d+[.)]\s/;
const BULLET_MARKER = /^[-•]\s/;

/** One item per line; a sub-item is indented and carries its marker
 *  (`1.` numbered, `-` bulleted), so the style survives the round trip. */
export function listToText(items: readonly RichTextListItem[]): string {
  return items
    .flatMap((item) => [
      spansToMarkup(item.content),
      ...(item.children?.items ?? []).map(
        (child, index) =>
          `  ${item.children?.style === "ordered" ? `${index + 1}.` : "-"} ${spansToMarkup(child.content)}`,
      ),
    ])
    .join("\n");
}

/** Inverse of `listToText`. A line indented by two spaces or a tab belongs to
 *  the item above it; deeper indentation flattens to that one level (the
 *  contract has two). Empty lines, and lines with nothing left after parsing,
 *  are skipped. */
export function textToListItems(text: string): RichTextListItem[] {
  const items: RichTextListItem[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "") continue;
    const parent = items[items.length - 1];
    if (CHILD_LINE.test(line) && parent) {
      const body = line.replace(/^[ \t]+/, "");
      const ordered = ORDERED_MARKER.test(body);
      const content = markupToSpans(
        body.replace(ordered ? ORDERED_MARKER : BULLET_MARKER, ""),
      );
      if (content.length === 0) continue;
      parent.children ??= {
        style: ordered ? "ordered" : "bullet",
        items: [],
      };
      parent.children.items.push({ content });
      continue;
    }
    // Only a first line can be indented without being a sub-item.
    const content = markupToSpans(parent ? line : line.replace(/^[ \t]+/, ""));
    if (content.length > 0) items.push({ content });
  }
  return items;
}

const BLANK_LINES = /\n(?:[^\S\n]*\n)+/;

export function hasBlankLines(text: string): boolean {
  return BLANK_LINES.test(text);
}

/** Text migrated from v1 is one paragraph holding every blank-line break of
 *  the original; this makes those breaks real paragraphs. Runs keep their
 *  marks across the cut, and nothing else changes. */
export function splitParagraph(
  node: Extract<RichTextNode, { type: "paragraph" }>,
): Extract<RichTextNode, { type: "paragraph" }>[] {
  const paragraphs: RichTextSpan[][] = [[]];
  for (const run of node.content) {
    run.text.split(BLANK_LINES).forEach((part, index) => {
      if (index > 0) paragraphs.push([]);
      paragraphs[paragraphs.length - 1].push({ ...run, text: part });
    });
  }
  return paragraphs
    .map((content) => normalizeSpans(content))
    .filter((content) => content.length > 0)
    .map((content) => ({ type: "paragraph" as const, content }));
}
