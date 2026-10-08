import { sitesPage } from "../../sites-page";

/** One content type's entries — the blog screen, for that type. */
export default async function SitesContentTypePage({
  params,
}: {
  params: Promise<{ typeId: string }>;
}) {
  const { typeId } = await params;
  return sitesPage("contentType", { typeId });
}
