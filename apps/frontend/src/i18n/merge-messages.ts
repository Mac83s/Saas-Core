type Messages = Record<string, unknown>;

const isTree = (value: unknown): value is Messages =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * Core's messages with a product's laid over them (ADR-049): a product adds
 * namespaces and keys at any depth and replaces the strings it names, but never
 * drops a key of core's. A shallow merge per namespace did — a product giving
 * `History.actions` one label of its own erased all of core's.
 */
export function mergeMessages(core: Messages, extra: Messages): Messages {
  const merged: Messages = { ...core };
  for (const [key, value] of Object.entries(extra)) {
    const base = merged[key];
    merged[key] =
      isTree(value) && isTree(base) ? mergeMessages(base, value) : value;
  }
  return merged;
}

/** `core` with each layer laid over it, in order; a missing layer is none. */
export function layerMessages(
  core: Messages,
  layers: readonly (Messages | undefined)[],
): Messages {
  return layers.reduce<Messages>(
    (merged, layer) => (layer ? mergeMessages(merged, layer) : merged),
    core,
  );
}

/**
 * Where the words of a product's public pages (ADR-080) lie among a
 * language's messages. A content language beyond the panel's two reads the
 * English catalogue (`catalogue`), so the product's English words lie under
 * the guest pages' texts in that language, and its own words in it come
 * last: a word it lacks in German is English, not a missing key.
 */
export function siteLayers(
  site: Readonly<Partial<Record<string, Messages>>>,
  locale: string,
  catalogue: string,
  guest: Messages,
): (Messages | undefined)[] {
  return [
    catalogue === locale ? undefined : site[catalogue],
    guest,
    site[locale],
  ];
}
