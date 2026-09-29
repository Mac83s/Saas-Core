import contract from "@saas-core/contracts/site-blocks/section-conversions.v1.json";

import { richTextAnchorSlug } from "./rich-text";
import type {
  BlockFieldDefinition,
  BlockRegistry,
  JsonObject,
  JsonValue,
  SiteBlock,
} from "./types";

type Pair = readonly [string, string];
type Placeholder = Readonly<Record<"pl" | "en", string>>;

/** One pair of `section-conversions.v1.json` (F4-C): how a section of one
 *  block type becomes another. */
export interface SectionConversion {
  readonly id: string;
  readonly version: number;
  readonly from: string;
  readonly to: string;
  readonly layout: string;
  readonly fields: readonly Pair[];
  readonly items?: {
    readonly from: string;
    readonly to: string;
    readonly max: number;
    readonly fields: readonly Pair[];
    readonly maxLength?: Readonly<Record<string, number>>;
    readonly fill?: Readonly<Record<string, Placeholder>>;
  };
  readonly sections?: {
    readonly from: string;
    readonly heading: string;
    readonly text: string;
    readonly level: 2 | 3 | 4;
    readonly fill: Placeholder;
  };
  readonly note?: string;
}

/** What stops a change: the target cannot hold the section as it is. */
export type ConversionBlocker =
  | { readonly kind: "tooMany"; readonly count: number; readonly max: number }
  | {
      readonly kind: "tooLong";
      readonly item: number;
      readonly field: string;
      readonly max: number;
    }
  | { readonly kind: "invalid" };

export interface SectionConversionResult {
  /** The section as the other type, or `null` when a blocker stops it. */
  readonly block: SiteBlock | null;
  /** Filled-in fields of the section the other type has no place for. */
  readonly lost: readonly {
    readonly field: BlockFieldDefinition;
    readonly parent?: BlockFieldDefinition;
  }[];
  /** Required fields the section left empty, now `[Uzupełnij: …]`. */
  readonly filled: number;
  readonly blockers: readonly ConversionBlocker[];
}

const conversions =
  contract.conversions as unknown as readonly SectionConversion[];

/** Every conversion the contract lists, for the contract tests. */
export function coreSectionConversions(): readonly SectionConversion[] {
  return conversions;
}

/** The types a section of `blockType` can become in this deployment. */
export function sectionConversions(
  blockType: string,
  registry: BlockRegistry,
): readonly SectionConversion[] {
  return conversions.filter(
    (conversion) =>
      conversion.from === blockType && registry.definitions.has(conversion.to),
  );
}

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function present(value: unknown): boolean {
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.some(present);
  if (isObject(value)) return Object.values(value).some(present);
  return value !== undefined && value !== null;
}

function at(data: unknown, path: readonly (string | number)[]): unknown {
  let value = data;
  for (const segment of path) {
    if (!isObject(value) && !Array.isArray(value)) return undefined;
    value = (value as Record<string | number, unknown>)[segment];
  }
  return value;
}

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() ? value : undefined;

/**
 * The section as another type, by the contract: named fields carried as they
 * are, a list item by item, or written out as headings and paragraphs. What
 * the contract does not carry is reported as `lost`, never dropped silently;
 * a required field the section lacks becomes a `[Uzupełnij: …]` marker the
 * editor already asks to fill in; anything the target cannot hold (too many
 * items, a text too long) stops the change and says where. The section keeps
 * its decoration, width and anchor — those belong to any section.
 */
export function convertSection(
  block: SiteBlock,
  conversion: SectionConversion,
  registry: BlockRegistry,
  locale: "pl" | "en",
): SectionConversionResult {
  let source: JsonObject;
  try {
    source = registry.migrate(block).data;
  } catch {
    // A section still being filled in (an FAQ without questions yet) is not
    // valid, and so not convertible — said, not thrown at the editor.
    return {
      block: null,
      lost: [],
      filled: 0,
      blockers: [{ kind: "invalid" }],
    };
  }
  const data: JsonObject = { layout: conversion.layout };
  const used = new Set<string>();
  const usedInItems = new Set<string>();
  const blockers: ConversionBlocker[] = [];
  let filled = 0;

  for (const [from, to] of conversion.fields) {
    used.add(from);
    if (present(source[from])) data[to] = structuredClone(source[from]!);
  }

  const entries = (key: string): unknown[] => {
    const value = source[key];
    return Array.isArray(value) ? value : [];
  };

  if (conversion.items) {
    const { from, to, max, fields, maxLength, fill } = conversion.items;
    used.add(from);
    const list = entries(from);
    if (list.length > max)
      blockers.push({ kind: "tooMany", count: list.length, max });
    data[to] = list.map((entry, index) => {
      const item: JsonObject = {};
      for (const [key, target] of fields) {
        usedInItems.add(key);
        const value = text(at(entry, [key]));
        if (value !== undefined) {
          const limit = maxLength?.[target];
          if (limit !== undefined && value.length > limit)
            blockers.push({
              kind: "tooLong",
              item: index,
              field: key,
              max: limit,
            });
          item[target] = value;
        } else if (fill?.[target]) {
          item[target] = fill[target][locale];
          filled += 1;
        }
      }
      return item;
    });
  }

  if (conversion.sections) {
    const { from, heading, text: body, level, fill } = conversion.sections;
    used.add(from);
    usedInItems.add(heading);
    usedInItems.add(body);
    const taken = new Set<string>();
    const content: JsonValue[] = [];
    for (const entry of entries(from)) {
      const title = text(at(entry, [heading]));
      if (title !== undefined) {
        const anchor = richTextAnchorSlug(title, taken);
        taken.add(anchor);
        content.push({ type: "heading", level, anchor, text: title.trim() });
      }
      const paragraph = text(at(entry, [body]));
      if (paragraph !== undefined)
        content.push({ type: "paragraph", content: [{ text: paragraph }] });
    }
    if (conversion.note) {
      used.add(conversion.note);
      const note = source[conversion.note];
      const noteText = text(at(note, ["text"]));
      const noteTitle = text(at(note, ["title"]));
      if (noteText !== undefined)
        content.push({
          type: "note",
          tone: "info",
          ...(noteTitle !== undefined ? { title: noteTitle } : {}),
          content: [{ text: noteText }],
        });
    }
    if (content.length === 0) {
      content.push({ type: "paragraph", content: [{ text: fill[locale] }] });
      filled += 1;
    }
    data.content = content;
  }

  const lost: {
    field: BlockFieldDefinition;
    parent?: BlockFieldDefinition;
  }[] = [];
  const definition = registry.definitions.get(block.block_type);
  for (const field of definition?.catalog?.fields ?? []) {
    const key = String(field.path[0]);
    if (field.kind === "list") {
      const list = entries(key);
      if (!used.has(key)) {
        if (list.some(present)) lost.push({ field });
        continue;
      }
      for (const item of field.item ?? [])
        if (
          !usedInItems.has(String(item.path[0])) &&
          list.some((entry) => present(at(entry, item.path)))
        )
          lost.push({ field: item, parent: field });
    } else if (!used.has(key) && present(at(source, field.path))) {
      lost.push({ field });
    }
  }

  const target = registry.definitions.get(conversion.to);
  const converted: SiteBlock = {
    block_type: conversion.to,
    schema_version: target?.latestVersion ?? 1,
    data,
    ...(block.decoration
      ? { decoration: structuredClone(block.decoration) }
      : {}),
    ...(block.presentation
      ? { presentation: structuredClone(block.presentation) }
      : {}),
  };
  if (blockers.length === 0) {
    try {
      registry.validate(converted);
    } catch {
      blockers.push({ kind: "invalid" });
    }
  }
  return {
    block: blockers.length ? null : converted,
    lost,
    filled,
    blockers,
  };
}
