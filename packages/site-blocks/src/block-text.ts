import type { BlockTextRenderer } from "./types";

/** Published pages keep plain strings. Only the panel supplies editor controls. */
export const plainBlockText: BlockTextRenderer = (_path, value) => value;
