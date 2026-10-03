import { headers } from "next/headers";

import { getPublicProjection } from "../../../../modules/shared/sites/public-projection";

export const dynamic = "force-dynamic";

/** A language's own feed, `/en/atom.xml` (TL14); the site's language has
 *  only `/atom.xml`, and the backend answers 404 for it here. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ locale: string }> },
) {
  const { locale } = await params;
  if (!/^[a-z]{2}$/.test(locale)) return new Response(null, { status: 404 });
  const host = (await headers()).get("host") ?? "";
  const result = await getPublicProjection(host, "atom.xml", locale);
  if (result.kind === "not-found") {
    return new Response(null, { status: 404 });
  }
  return new Response(result.body, {
    headers: { "content-type": result.contentType },
  });
}
