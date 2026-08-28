import { headers } from "next/headers";

import { getPublicProjection } from "../../../modules/shared/sites/public-projection";

export const dynamic = "force-dynamic";

export async function GET() {
  const host = (await headers()).get("host") ?? "";
  const result = await getPublicProjection(host, "sitemap.xml");
  if (result.kind === "not-found") {
    return new Response(null, { status: 404 });
  }
  return new Response(result.body, {
    headers: { "content-type": result.contentType },
  });
}
