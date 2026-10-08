import { headers } from "next/headers";

import { platformMedia } from "#lib/product-site/media";

export const dynamic = "force-dynamic";

/** A picture of the platform's own published content (ADR-079 pkt 30). */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ assetId: string }> },
) {
  const { assetId } = await params;
  return platformMedia((await headers()).get("host"), assetId);
}
