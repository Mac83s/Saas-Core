/** Canonical rich text runs (`core.rich_text` spans): what the editor, the
 *  clipboard normalizer and the stored JSON agree on. */

import type { RichTextNode, RichTextSpan } from "@saas-core/site-blocks";

const HREF_PATTERN =
  /^(?:\/(?!\/)|https:\/\/|mailto:|tel:|#[a-z][a-z0-9-]{0,63}$)/;
const MAX_SPAN_TEXT = 4000;

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
