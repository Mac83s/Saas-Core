import { headers } from "next/headers";

import { getPublicProjection } from "../../../modules/shared/sites/public-projection";

export const dynamic = "force-dynamic";

/** `/llms.txt`: the site's map for a language model, in its own language (TL19). */
export async function GET() {
  const host = (await headers()).get("host") ?? "";
  const result = await getPublicProjection(host, "llms.txt");
  if (result.kind === "not-found") {
    return new Response(null, { status: 404 });
  }
  return new Response(result.body, {
    headers: { "content-type": result.contentType },
  });
}
