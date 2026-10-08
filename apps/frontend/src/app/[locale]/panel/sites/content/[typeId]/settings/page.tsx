import { sitesPage } from "../../../sites-page";

/** What one content type is: name, address, feeds, menu, switching it off. */
export default async function SitesContentTypeSettingsPage({
  params,
}: {
  params: Promise<{ typeId: string }>;
}) {
  const { typeId } = await params;
  return sitesPage("contentTypeSettings", { typeId });
}
