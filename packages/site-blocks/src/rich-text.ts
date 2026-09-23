import type { JsonObject, JsonValue, RichTextNode, SiteBlock } from "./types";

const ANCHOR_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;

const TRANSLITERATION: Readonly<Record<string, string>> = {
  ą: "a",
  ć: "c",
  ę: "e",
  ł: "l",
  ń: "n",
  ó: "o",
  ś: "s",
  ź: "z",
  ż: "z",
};

/** A stable heading anchor made from its text once, when the heading is
 *  created. Later edits of the text never recompute it (links would break).
 *  `taken` holds anchors already used on the page; a collision gets `-2`, `-3`…
 *  Text with no usable letters falls back to `section`. */
export function richTextAnchorSlug(
  text: string,
  taken: ReadonlySet<string> = new Set(),
): string {
  const base =
    text
      .toLowerCase()
      .replace(/[ąćęłńóśźż]/g, (letter) => TRANSLITERATION[letter] ?? letter)
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^[^a-z]+/, "")
      .replace(/-+$/, "")
      .slice(0, 56)
      .replace(/-+$/, "") || "section";
  if (!taken.has(base)) return base;
  for (let suffix = 2; ; suffix += 1) {
    const candidate = `${base}-${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
}

export function isRichTextAnchor(value: string): boolean {
  return ANCHOR_PATTERN.test(value);
}

/** Every media asset id a block's data points at, wherever it sits: a hero
 *  photo, a product gallery, a figure inside rich text. The convention across
 *  all block schemas is that `asset_id` names a media asset and nothing else,
 *  so the walk needs no per-type knowledge. Order is first occurrence. */
export function blockAssetIds(data: JsonValue | undefined): string[] {
  const found: string[] = [];
  const visit = (value: JsonValue | undefined): void => {
    if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (value !== null && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        if (
          key === "asset_id" &&
          typeof child === "string" &&
          child.length > 0
        ) {
          if (!found.includes(child)) found.push(child);
        } else {
          visit(child);
        }
      }
    }
  };
  visit(data);
  return found;
}

/** Sets `value` at `path` inside `target` (mutates). The parent must already
 *  exist; the last segment is a key of an object, or an index into an array no
 *  greater than its length (equal appends). Anything else is a recipe error. */
export function setAtPath(
  target: JsonObject,
  path: readonly (string | number)[],
  value: JsonValue,
): void {
  if (path.length === 0) throw new TypeError("Pusta ścieżka.");
  let parent: JsonValue = target;
  for (const segment of path.slice(0, -1)) {
    const next: JsonValue | undefined = Array.isArray(parent)
      ? typeof segment === "number"
        ? parent[segment]
        : undefined
      : parent !== null && typeof parent === "object"
        ? typeof segment === "string"
          ? parent[segment]
          : undefined
        : undefined;
    if (next === undefined || next === null || typeof next !== "object") {
      throw new TypeError(`Ścieżka ${path.join(".")} nie istnieje.`);
    }
    parent = next;
  }
  const last = path[path.length - 1];
  if (Array.isArray(parent)) {
    if (typeof last !== "number" || last < 0 || last > parent.length) {
      throw new TypeError(`Indeks ${String(last)} poza tablicą.`);
    }
    parent[last] = value;
    return;
  }
  if (parent === null || typeof parent !== "object" || typeof last !== "string")
    throw new TypeError(`Ścieżka ${path.join(".")} nie wskazuje obiektu.`);
  parent[last] = value;
}

function richTextHeadings(
  block: SiteBlock,
): Extract<RichTextNode, { type: "heading" }>[] {
  const content = block.data.content;
  if (block.block_type !== "core.rich_text" || !Array.isArray(content))
    return [];
  return (content as unknown as RichTextNode[]).filter(
    (node) => node.type === "heading",
  );
}

/** Heading anchors of the given blocks' rich text, in page order. */
export function richTextAnchors(blocks: readonly SiteBlock[]): string[] {
  return blocks.flatMap((block) =>
    richTextHeadings(block).map((heading) => heading.anchor),
  );
}

function rewriteHrefs(value: JsonValue, renamed: Map<string, string>): void {
  if (Array.isArray(value)) {
    value.forEach((child) => rewriteHrefs(child, renamed));
  } else if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (
        key === "href" &&
        typeof child === "string" &&
        child.startsWith("#")
      ) {
        const target = renamed.get(child.slice(1));
        if (target !== undefined) value[key] = `#${target}`;
      } else {
        rewriteHrefs(child, renamed);
      }
    }
  }
}

/** Anchors are unique within a page. Inserting, duplicating or importing a
 *  section renames a later duplicate (`-2`, `-3`…) and rewrites the renamed
 *  section's own `#anchor` links with it. `existing` holds anchors already on
 *  the page outside `blocks`. Changed blocks are copies; the input stays. */
export function ensureUniqueAnchors(
  blocks: readonly SiteBlock[],
  existing: ReadonlySet<string> = new Set(),
): SiteBlock[] {
  const taken = new Set(existing);
  return blocks.map((block) => {
    const headings = richTextHeadings(block);
    if (headings.every((heading) => !taken.has(heading.anchor))) {
      headings.forEach((heading) => taken.add(heading.anchor));
      return block;
    }
    const copy: SiteBlock = { ...block, data: structuredClone(block.data) };
    const kept = new Set<string>();
    const renamed = new Map<string, string>();
    for (const heading of richTextHeadings(copy)) {
      if (taken.has(heading.anchor)) {
        const anchor = richTextAnchorSlug(heading.anchor, taken);
        if (!renamed.has(heading.anchor)) renamed.set(heading.anchor, anchor);
        heading.anchor = anchor;
      } else {
        kept.add(heading.anchor);
      }
      taken.add(heading.anchor);
    }
    // A link keeps its target while one heading of this section still owns
    // the old anchor; otherwise it follows the rename.
    for (const anchor of kept) renamed.delete(anchor);
    rewriteHrefs(copy.data, renamed);
    return copy;
  });
}

const PLACEHOLDER = /\[(?:Uzupełnij|Fill in):[^\]]*\]/g;

export interface UnfilledPlaceholder {
  /** Position of the block on the page. */
  readonly blockIndex: number;
  /** Path of the string inside the block's data, as the editor adapter uses. */
  readonly path: readonly string[];
  /** The marker itself, e.g. "[Uzupełnij: prawdziwa opinia klienta]". */
  readonly text: string;
}

/** Places a template left for the owner's real material — reviews, numbers,
 *  references — written as `[Uzupełnij: …]` (EN `[Fill in: …]`). Templates
 *  never invent proof, so a marker still on the page is something to finish
 *  before publishing, not a typo. */
export function unfilledPlaceholders(
  blocks: readonly { data: JsonObject }[],
): UnfilledPlaceholder[] {
  const found: UnfilledPlaceholder[] = [];
  blocks.forEach((block, blockIndex) => {
    const visit = (value: JsonValue, path: string[]): void => {
      if (typeof value === "string") {
        for (const match of value.matchAll(PLACEHOLDER))
          found.push({ blockIndex, path, text: match[0] });
      } else if (Array.isArray(value)) {
        value.forEach((child, index) => visit(child, [...path, String(index)]));
      } else if (value !== null && typeof value === "object") {
        for (const [key, child] of Object.entries(value))
          visit(child, [...path, key]);
      }
    };
    visit(block.data, []);
  });
  return found;
}
