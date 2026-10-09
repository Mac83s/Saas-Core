import { companyOnly } from "#lib/company-only";
import { sitesPage } from "../../sites-page";

export default async function SitePageEditorPage({
  params,
  searchParams,
}: {
  params: Promise<{ pageId: string }>;
  searchParams: Promise<{ preview?: string }>;
}) {
  await companyOnly();
  const [{ pageId }, { preview }] = await Promise.all([params, searchParams]);
  return sitesPage("page", { pageId, preview: preview === "1" });
}
