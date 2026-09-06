import { notFound } from "next/navigation";
import { deployment } from "../../../../../generated/deployment";
import { SeoGscPanel } from "../../../../../modules/shared/seo/gsc-panel";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SearchConsolePage() {
  if (!new Set<string>(deployment.modules).has("shared.seo")) notFound();
  const organization = await getServerCurrentOrganization();
  return (
    <main className="mx-auto w-full max-w-7xl px-5 py-10">
      <SeoGscPanel key={organization?.id ?? "no-organization"} />
    </main>
  );
}
