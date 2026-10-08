import { sitesPage } from "../../../sites-page";

/** A content type's categories: names, tree, addresses, removing. */
export default async function SitesContentTypeCategoriesPage({
  params,
}: {
  params: Promise<{ typeId: string }>;
}) {
  const { typeId } = await params;
  return sitesPage("contentTypeCategories", { typeId });
}
