import { cloneElement, type ReactElement } from "react";

import { withAiBadge } from "./ai-badge";
import type { BlockImageRenderer, ImageSize, JsonObject } from "./types";

/** How many pictures at the top of a page load with it instead of waiting to
 *  be scrolled to. Two: an audit reads the first two of a document as its
 *  first screen, and a unit's card shows its cover with the next photo beside
 *  it. */
export const LEADING_IMAGES = 2;

type Img = ReactElement<{
  alt?: string;
  width?: number;
  height?: number;
  loading?: "lazy" | "eager";
}>;

/** Whether a block's data — or what a live block shows now — names a
 *  picture: a media reference (`asset_id`) or an asset the page knows. */
export function namesPicture(
  value: unknown,
  known: ReadonlySet<string>,
): boolean {
  if (typeof value === "string") return known.has(value);
  if (Array.isArray(value))
    return value.some((item) => namesPicture(item, known));
  if (value === null || typeof value !== "object") return false;
  return Object.entries(value as JsonObject).some(
    ([key, item]) =>
      (key === "asset_id" && typeof item === "string") ||
      namesPicture(item, known),
  );
}

/**
 * What a published page adds to each block's own `<img>`: its stored size,
 * the visible AI marking (ADR-059 pkt 7), and — in the first block that shows
 * pictures (`leading`) — eager loading for the first `LEADING_IMAGES` of them.
 * The pictures a block loads eagerly are remembered by asset, not counted by
 * call: a block's component may be called more than once for one page.
 */
export function publishedImageRenderer({
  sizes,
  aiIds,
  locale,
}: {
  sizes: Readonly<Record<string, ImageSize>>;
  aiIds: ReadonlySet<string>;
  locale: string;
}): (leading: boolean) => BlockImageRenderer {
  const eager = new Set<string>();
  return (leading) => (image, element) => {
    const size = sizes[image.asset_id];
    if (leading && eager.size < LEADING_IMAGES) eager.add(image.asset_id);
    const sized = cloneElement(element as Img, {
      ...(size ? { width: size.width, height: size.height } : {}),
      ...(leading && eager.has(image.asset_id) ? { loading: "eager" } : {}),
    });
    return aiIds.has(image.asset_id) ? withAiBadge(sized, locale) : sized;
  };
}
