import { companyOnly } from "#lib/company-only";
import { sitesPage } from "../sites-page";

export default async function SitesMenuPage() {
  await companyOnly();
  return sitesPage("menu");
}
