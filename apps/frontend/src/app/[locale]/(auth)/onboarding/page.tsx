import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { getServerOrganizations, getServerUser } from "#lib/server-auth";
import { AuthShell } from "../../../../modules/core/identity";
import { OrganizationOnboarding } from "../../../../modules/core/organizations";

export default async function OnboardingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const [{ locale }, user, organizations, t] = await Promise.all([
    params,
    getServerUser(),
    getServerOrganizations(),
    getTranslations("Onboarding"),
  ]);
  const prefix = locale === "pl" ? "" : `/${locale}`;
  if (!user) redirect(`${prefix}/login`);
  if (organizations.length > 0) redirect(`${prefix}/panel`);
  return (
    <AuthShell description={t("description")} title={t("title")}>
      <OrganizationOnboarding />
    </AuthShell>
  );
}
