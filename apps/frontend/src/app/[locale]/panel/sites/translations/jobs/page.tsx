import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { TranslationJobsPanel } from "../../../../../../modules/shared/translation/jobs-panel";

/** „Tłumaczenia → Zadania”: only where the product has the engine. */
export default async function TranslationJobsPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.translation"))
    notFound();
  return <TranslationJobsPanel key={organization?.id ?? "no-organization"} />;
}
