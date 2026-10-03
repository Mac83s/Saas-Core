import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { TranslationReviewPanel } from "../../../../../../modules/shared/translation/review-panel";

/** „Tłumaczenia → Do akceptacji”: only where the product has the engine. */
export default async function TranslationReviewPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.translation"))
    notFound();
  return <TranslationReviewPanel key={organization?.id ?? "no-organization"} />;
}
