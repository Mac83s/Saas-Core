import { headers } from "next/headers";

import { getPublicMedia } from "../../../../../modules/shared/sites/public-projection";

export const dynamic = "force-dynamic";

const VARIANTS = new Set(["thumbnail", "preview"]);

/** A published picture's WebP copy (F4-P3), for `srcset`: the same host
 *  check as the original, and only the two copies the pipeline makes. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ assetId: string; variant: string }> },
) {
  const { assetId, variant } = await params;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      assetId,
    ) ||
    !VARIANTS.has(variant)
  ) {
    return new Response(null, { status: 404 });
  }
  const host = (await headers()).get("host") ?? "";
  const result = await getPublicMedia(
    host,
    assetId,
    variant as "thumbnail" | "preview",
  );
  if (result.kind === "not-found") return new Response(null, { status: 404 });
  return new Response(new Uint8Array(result.body), {
    headers: {
      "content-type": result.contentType,
      "cache-control": result.cacheControl,
      "x-content-type-options": "nosniff",
    },
  });
}
