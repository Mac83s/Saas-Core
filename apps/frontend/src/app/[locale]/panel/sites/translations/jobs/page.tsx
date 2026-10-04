import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { TranslationJobsPanel } from "../../../../../../modules/shared/translation/jobs-panel";

/** „Tłumaczenia → Zadania”: only where the product has the engine. */
export default async function TranslationJobsPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string }>;
}) {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.translation"))
    notFound();
  const view = (await searchParams)?.state === "held" ? "held" : "";
  return (
    <TranslationJobsPanel
      initialView={view}
      key={`${organization?.id ?? "no-organization"}:${view}`}
    />
  );
}
