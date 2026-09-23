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
