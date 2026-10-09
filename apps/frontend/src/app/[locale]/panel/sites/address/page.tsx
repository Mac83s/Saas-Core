import { companyOnly } from "#lib/company-only";
import { sitesPage } from "../sites-page";

export default async function SitesAddressPage() {
  await companyOnly();
  return sitesPage("address");
}
