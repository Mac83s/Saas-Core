import { sitesPage } from "../../../sites-page";

/** The site's tags as one content type shows them: names, addresses, removing. */
export default async function SitesContentTypeTagsPage({
  params,
}: {
  params: Promise<{ typeId: string }>;
}) {
  const { typeId } = await params;
  return sitesPage("contentTypeTags", { typeId });
}
