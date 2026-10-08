import "server-only";

import { isControlHostname, normalizeRequestHostname } from "../../proxy-host";

const ASSET_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const VARIANTS: ReadonlySet<string> = new Set(["thumbnail", "preview"]);
/** What the media pipeline keeps: raster pictures, never a document that
 *  could run in the panel's origin. */
const PICTURES: ReadonlySet<string> = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

const notFound = () => new Response(null, { status: 404 });

/**
 * A picture of the platform's own published content, at `/media/<asset id>`
 * on the platform's host (ADR-079 pkt 30) — or one of its WebP copies. The
 * block renderers write that address relative to the host their page is on,
 * and a product's own pages are on this one.
 *
 * The backend answers only for a picture a published entry of the platform
 * workspace shows; everything else is the same 404. A company's site keeps
 * its own `/media/…`, behind its own host: the proxy hands every address of
 * a company's host to the renderer, and this refuses any host that is not
 * the platform's as well.
 */
export async function platformMedia(
  host: string | null,
  assetId: string,
  variant?: string,
): Promise<Response> {
  if (
    !isControlHostname(normalizeRequestHostname(host)) ||
    !ASSET_ID.test(assetId) ||
    (variant !== undefined && !VARIANTS.has(variant))
  ) {
    return notFound();
  }
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const response = await fetch(
    new URL(
      `/api/v1/public/content/media/${assetId.toLowerCase()}/${variant ? `${variant}/` : ""}`,
      backend,
    ),
    { cache: "no-store" },
  );
  if (response.status === 404) return notFound();
  if (!response.ok) {
    throw new Error(`Public content API answered ${response.status}`);
  }
  const contentType = (response.headers.get("content-type") ?? "")
    .split(";")[0]!
    .trim()
    .toLowerCase();
  if (!PICTURES.has(contentType)) return notFound();
  return new Response(await response.arrayBuffer(), {
    headers: {
      "content-type": contentType,
      "cache-control": response.headers.get("cache-control") ?? "no-store",
      // This is the panel's origin: the bytes are a picture and nothing a
      // browser may run or reinterpret.
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'none'; sandbox",
    },
  });
}
