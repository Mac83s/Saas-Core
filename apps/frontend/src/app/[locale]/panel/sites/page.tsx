import { companyOnly } from "#lib/company-only";
import { sitesPage } from "./sites-page";

export default async function SitesPage() {
  await companyOnly();
  return sitesPage("pages");
}
