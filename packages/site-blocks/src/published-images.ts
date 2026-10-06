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

/** The pictures a block's data — or what a live block shows now — names:
 *  media references (`asset_id`) and assets the page knows, added to
 *  `found`. */
export function picturesNamed(
  value: unknown,
  known: ReadonlySet<string>,
  found: Set<string> = new Set(),
): Set<string> {
  if (typeof value === "string") {
    if (known.has(value)) found.add(value);
  } else if (Array.isArray(value)) {
    for (const item of value) picturesNamed(item, known, found);
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value as JsonObject)) {
      if (key === "asset_id" && typeof item === "string") found.add(item);
      else picturesNamed(item, known, found);
    }
  }
  return found;
}

/**
 * What a published page adds to each block's own `<img>`: its stored size,
 * the visible AI marking (ADR-059 pkt 7), and eager loading for the block's
 * first `eager` pictures — the page says how many (`leadingImages`). The
 * pictures a block loads eagerly are remembered by asset, not counted by
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
}): (eager: number) => BlockImageRenderer {
  return (eager) => {
    const first = new Set<string>();
    return (image, element) => {
      const size = sizes[image.asset_id];
      if (first.size < eager) first.add(image.asset_id);
      const sized = cloneElement(element as Img, {
        ...(size ? { width: size.width, height: size.height } : {}),
        ...(first.has(image.asset_id) ? { loading: "eager" } : {}),
      });
      return aiIds.has(image.asset_id) ? withAiBadge(sized, locale) : sized;
    };
  };
}

/**
 * How many of each block's first pictures load with the page, given how many
 * pictures each block names. The first block that shows any takes the first
 * screen's worth; where it names fewer — a unit with one photo, its map and
 * the other units' covers under it — the next block that shows pictures
 * loads the rest. Counted from what the blocks name, never from the order
 * their components happen to be called in.
 */
export function leadingImages(named: readonly number[]): number[] {
  const first = named.findIndex((count) => count > 0);
  const left = first < 0 ? 0 : LEADING_IMAGES - named[first]!;
  const next =
    left > 0 ? named.findIndex((count, at) => at > first && count > 0) : -1;
  return named.map((_count, at) =>
    at === first ? LEADING_IMAGES : at === next ? left : 0,
  );
}
