import { companyOnly } from "#lib/company-only";
import { sitesPage } from "../sites-page";

export default async function SitesPublicationPage() {
  await companyOnly();
  return sitesPage("publication");
}
