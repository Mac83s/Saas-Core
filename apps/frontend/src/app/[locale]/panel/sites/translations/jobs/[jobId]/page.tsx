import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { TranslationJobDetail } from "../../../../../../../modules/shared/translation/job-detail";

/** One translation job: only where the product has the engine. */
export default async function TranslationJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.translation"))
    notFound();
  return (
    <TranslationJobDetail
      jobId={jobId}
      key={`${organization?.id ?? "no-organization"}:${jobId}`}
    />
  );
}
