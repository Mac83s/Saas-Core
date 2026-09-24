import { isValidElement, type ReactElement, type ReactNode } from "react";

import type {
  BlockFieldDefinition,
  BlockRegistry,
  JsonValue,
  SiteBlock,
} from "./types";

/** A filled-in field the block's current layout does not show. `parent` is
 *  the list it belongs to, for a field of a list entry. */
export interface HiddenField {
  readonly field: BlockFieldDefinition;
  readonly parent?: BlockFieldDefinition;
}

type Path = readonly (string | number)[];

function at(data: JsonValue | undefined, path: Path): JsonValue | undefined {
  let value = data;
  for (const segment of path) {
    if (value === null || typeof value !== "object") return undefined;
    value = (value as Record<string, JsonValue>)[segment as string];
  }
  return value;
}

const filled = (value: JsonValue | undefined) =>
  typeof value === "string"
    ? value.trim() !== ""
    : Array.isArray(value) && value.length > 0;

/** Every text path and image a render of the block reads. Block components
 *  are plain functions without hooks (the registry relies on this too), so
 *  the tree is walked by calling them; nothing is mounted. */
function reads(block: SiteBlock, registry: BlockRegistry) {
  const texts: string[] = [];
  const images = new Set<string>();
  const walk = (node: ReactNode): void => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (!isValidElement(node)) return;
    const element = node as ReactElement<{ children?: ReactNode }>;
    if (typeof element.type === "function")
      return walk(
        (element.type as (props: unknown) => ReactNode)(element.props),
      );
    walk(element.props.children);
  };
  walk(
    registry.render(
      block,
      "hidden-fields",
      {
        text: (path, value) => {
          texts.push(path.join("."));
          return value;
        },
      },
      (image) => {
        images.add(image.asset_id);
        return null;
      },
    ),
  );
  return { texts, images };
}

/** The filled-in fields one render leaves out, as `parent.field` keys. */
function missing(
  block: SiteBlock,
  registry: BlockRegistry,
  fields: readonly BlockFieldDefinition[],
): Map<string, HiddenField> {
  const seen = reads(block, registry);
  const shown = (path: Path) => {
    const key = path.join(".");
    return seen.texts.some(
      (read) => read === key || read.startsWith(`${key}.`),
    );
  };
  const hidden = (field: BlockFieldDefinition, base: Path, data: JsonValue) => {
    const value = at(data, field.path);
    if (!filled(value)) return false;
    if (field.kind === "media")
      return typeof value === "string" && !seen.images.has(value);
    if (
      field.kind === "text" ||
      field.kind === "textarea" ||
      field.kind === "richText"
    )
      return !shown([...base, ...field.path]);
    return false;
  };
  const result = new Map<string, HiddenField>();
  for (const field of fields) {
    if (field.kind !== "list") {
      if (hidden(field, [], block.data))
        result.set(field.path.join("."), { field });
      continue;
    }
    const entries = at(block.data, field.path);
    if (!Array.isArray(entries)) continue;
    for (const item of field.item ?? [])
      if (
        entries.some((entry, index) =>
          hidden(item, [...field.path, index], entry),
        )
      )
        result.set(`${field.path.join(".")}.${item.path.join(".")}`, {
          field: item,
          parent: field,
        });
  }
  return result;
}

/** Which filled-in fields the block's layout leaves out although another
 *  layout of the same block shows them. The data stays in the block (a layout
 *  change never drops content); this tells the editor what a reader will not
 *  see until the layout changes again. A field no layout shows as such (a
 *  confirmation shown after sending, a link label without its address) is
 *  not the layout's doing and is not reported. Only text, rich text and
 *  photos are judged — links and choices have no text of their own. */
export function hiddenFields(
  block: SiteBlock,
  registry: BlockRegistry,
): HiddenField[] {
  try {
    const migrated = registry.migrate(block);
    const definition = registry.definitions.get(migrated.block_type);
    const fields = definition?.catalog?.fields ?? [];
    const current = missing(migrated, registry, fields);
    if (current.size === 0) return [];
    const latest = definition?.schemas.find(
      ({ version }) => version === definition.latestVersion,
    )?.schema as { properties?: { layout?: { enum?: unknown[] } } } | undefined;
    const layouts = (latest?.properties?.layout?.enum ?? []).filter(
      (layout): layout is string =>
        typeof layout === "string" && layout !== migrated.data.layout,
    );
    const others = layouts.map((layout) =>
      missing(
        { ...migrated, data: { ...migrated.data, layout } },
        registry,
        fields,
      ),
    );
    return [...current].flatMap(([key, hidden]) =>
      others.some((other) => !other.has(key)) ? [hidden] : [],
    );
  } catch {
    // A half-typed value may not render; the notice waits for a valid one.
    return [];
  }
}
