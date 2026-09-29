import { createElement as h, type ReactElement } from "react";

/** Most pictures sit in half a page on a computer and across a phone. */
export const HALF_WIDTH = "(min-width: 64rem) 50vw, 100vw";
/** A picture across the page on every screen. */
export const FULL_WIDTH = "100vw";

/**
 * A published picture with the WebP copies the media pipeline makes of every
 * image (F4-P3): a 320 px thumbnail and a 1280 px preview, served by the same
 * publication check as the original, which stays for screens that need more.
 * The widths are the copies' bounding boxes — a portrait copy is narrower —
 * and the original is announced as 2560 px; the browser only needs them to
 * choose, and a gallery of twelve photos no longer downloads twelve originals.
 */
export function publicImage(
  image: { asset_id: string; alt: string },
  {
    sizes = HALF_WIDTH,
    loading = "lazy",
  }: { sizes?: string; loading?: "lazy" | "eager" } = {},
): ReactElement<{ alt?: string }> {
  const base = `/media/${image.asset_id}`;
  return h("img", {
    src: base,
    srcSet: `${base}/thumbnail 320w, ${base}/preview 1280w, ${base} 2560w`,
    sizes,
    alt: image.alt,
    loading,
    decoding: "async",
  });
}
