import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { TranslationReviewPanel } from "../../../../../../modules/shared/translation/review-panel";

/** „Tłumaczenia → Do akceptacji”: only where the product has the engine —
 *  with websites or without (a document for customers is translated too). */
export default async function TranslationReviewPage() {
  const organization = await getServerCurrentOrganization();
  const modules = modulesFor(organization?.organization_type);
  if (!modules.has("shared.translation")) notFound();
  return (
    <TranslationReviewPanel
      key={organization?.id ?? "no-organization"}
      website={modules.has("shared.sites")}
    />
  );
}
