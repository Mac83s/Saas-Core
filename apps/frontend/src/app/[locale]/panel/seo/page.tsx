import { notFound } from "next/navigation";
import { deployment } from "../../../../generated/deployment";
import { SeoAuditsPanel } from "../../../../modules/shared/seo";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SeoAuditsPage() {
  if (!new Set<string>(deployment.modules).has("shared.seo")) notFound();
  const organization = await getServerCurrentOrganization();
  return (
    <main className="mx-auto w-full max-w-7xl px-5 py-10">
      <SeoAuditsPanel key={organization?.id ?? "no-organization"} />
    </main>
  );
}
