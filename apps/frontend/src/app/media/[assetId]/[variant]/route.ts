import { headers } from "next/headers";

import { platformMedia } from "#lib/product-site/media";

export const dynamic = "force-dynamic";

/** A WebP copy of a picture of the platform's own published content. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ assetId: string; variant: string }> },
) {
  const { assetId, variant } = await params;
  return platformMedia((await headers()).get("host"), assetId, variant);
}
