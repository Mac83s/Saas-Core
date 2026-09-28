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

function setAt(
  target: Record<string, JsonValue>,
  path: Path,
  value: JsonValue,
) {
  let node = target;
  for (const segment of path.slice(0, -1)) {
    const next = node[segment as string];
    if (next === null || typeof next !== "object" || Array.isArray(next))
      node[segment as string] = {};
    node = node[segment as string] as Record<string, JsonValue>;
  }
  node[path[path.length - 1] as string] = value;
}

/** Every catalogue field filled in, one entry per list: what a layout would
 *  show if the owner wrote everything. Each photo gets its own id, keyed like
 *  the field, so a render can tell which one it drew. */
function filledIn(
  fields: readonly BlockFieldDefinition[],
  photos: Map<string, string>,
  prefix = "",
) {
  const data: Record<string, JsonValue> = {};
  for (const field of fields) {
    const key = prefix + field.path.join(".");
    let value: JsonValue;
    // Three entries: as many as a comparison has columns.
    if (field.kind === "list")
      value = [0, 1, 2].map(() =>
        filledIn(field.item ?? [], photos, `${key}.`),
      );
    else if (field.kind === "richText")
      value = [{ type: "paragraph", content: [{ text: "x" }] }];
    else if (field.kind === "media") {
      value = `00000000-0000-4000-8000-${String(photos.size + 1).padStart(12, "0")}`;
      photos.set(key, value);
    } else if (field.kind === "url") value = "/x";
    else if (field.kind === "choice") value = field.options?.[0] ?? "";
    else value = "x";
    setAt(data, field.path, value);
  }
  return data;
}

/** Keys (`path`, or `list.itemPath` for a list entry's field) of the fields a
 *  render of `layout` shows once filled in. A link or a choice counts as shown
 *  when a text or photo beside it is; one with nothing beside it always does. */
function shownKeys(
  type: string,
  layout: string | undefined,
  fields: readonly BlockFieldDefinition[],
  registry: BlockRegistry,
): Set<string> {
  const photos = new Map<string, string>();
  const data = filledIn(fields, photos);
  if (layout !== undefined) data.layout = layout;
  const definition = registry.definitions.get(type)!;
  const seen = reads(
    { block_type: type, schema_version: definition.latestVersion, data },
    registry,
  );
  const shown = new Set<string>();
  const visit = (
    list: readonly BlockFieldDefinition[],
    base: Path,
    prefix: string,
  ) => {
    const read = (field: BlockFieldDefinition) => {
      if (field.kind === "media")
        return seen.images.has(photos.get(prefix + field.path.join("."))!);
      const own = [...base, ...field.path].join(".");
      return seen.texts.some((key) => key === own || key.startsWith(`${own}.`));
    };
    const drawn = list.filter((field) =>
      ["text", "textarea", "richText", "media"].includes(field.kind),
    );
    const beside = (field: BlockFieldDefinition) =>
      drawn.filter(
        (other) =>
          other !== field &&
          other.path.slice(0, -1).join(".") ===
            field.path.slice(0, -1).join("."),
      );
    // A text no render reads (an image's alt) goes with the photo beside it.
    const shows = (field: BlockFieldDefinition): boolean =>
      read(field) ||
      (field.kind !== "media" &&
        beside(field).some((other) => other.kind === "media" && read(other)));
    for (const field of list) {
      const key = prefix + field.path.join(".");
      if (field.kind === "list") {
        const before = shown.size;
        visit(field.item ?? [], [...base, ...field.path, 0], `${key}.`);
        if (shown.size > before) shown.add(key);
      } else if (drawn.includes(field)) {
        if (shows(field)) shown.add(key);
      } else if (beside(field).length === 0 || beside(field).some(shows))
        shown.add(key);
    }
  };
  visit(fields, [], "");
  return shown;
}

const onlyElsewhere = new WeakMap<
  BlockRegistry,
  Map<string, ReadonlySet<string>>
>();

/** Keys of the fields the block's current layout never shows although another
 *  layout of the block does. The inspector leaves such a field out while it is
 *  empty — a list of cards does not ask for comparison columns — and keeps it
 *  once filled, where `hiddenFields` says the layout does not show it. A field
 *  no layout shows as such (a form's labels, drawn by the form renderer) is
 *  never left out. Keys as in `HiddenField`: `path`, or `list.itemPath`. */
export function fieldsOfOtherLayouts(
  block: Pick<SiteBlock, "block_type" | "data">,
  registry: BlockRegistry,
): ReadonlySet<string> {
  const definition = registry.definitions.get(block.block_type);
  const fields = definition?.catalog?.fields;
  const schema = definition?.schemas.find(
    ({ version }) => version === definition.latestVersion,
  )?.schema as { properties?: { layout?: { enum?: unknown[] } } } | undefined;
  const layouts = (schema?.properties?.layout?.enum ?? []).filter(
    (layout): layout is string => typeof layout === "string",
  );
  if (!fields || layouts.length < 2) return new Set();
  const layout =
    typeof block.data.layout === "string" ? block.data.layout : undefined;
  const cache = onlyElsewhere.get(registry) ?? new Map();
  onlyElsewhere.set(registry, cache);
  const cacheKey = `${block.block_type}@${layout ?? ""}`;
  if (!cache.has(cacheKey)) {
    let result: ReadonlySet<string> = new Set();
    try {
      const current = shownKeys(block.block_type, layout, fields, registry);
      const anywhere = new Set(
        layouts.flatMap((other) => [
          ...shownKeys(block.block_type, other, fields, registry),
        ]),
      );
      result = new Set([...anywhere].filter((key) => !current.has(key)));
    } catch {
      // A block whose filled-in render fails keeps every field.
    }
    cache.set(cacheKey, result);
  }
  return cache.get(cacheKey)!;
}
