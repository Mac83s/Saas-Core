import { headers } from "next/headers";

import { getPublicMedia } from "../../../../modules/shared/sites/public-projection";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ assetId: string }> },
) {
  const { assetId } = await params;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      assetId,
    )
  ) {
    return new Response(null, { status: 404 });
  }
  const host = (await headers()).get("host") ?? "";
  const result = await getPublicMedia(host, assetId);
  if (result.kind === "not-found") return new Response(null, { status: 404 });
  return new Response(new Uint8Array(result.body), {
    headers: {
      "content-type": result.contentType,
      "cache-control": result.cacheControl,
      "x-content-type-options": "nosniff",
    },
  });
}
