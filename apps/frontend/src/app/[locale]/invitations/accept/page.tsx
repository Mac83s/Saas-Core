import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { getServerUser } from "#lib/server-auth";
import { AuthShell } from "../../../../modules/core/identity";
import { InvitationAcceptance } from "../../../../modules/core/organizations";

export default async function InvitationAcceptPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ token?: string }>;
}) {
  const [{ locale }, { token }, t] = await Promise.all([
    params,
    searchParams,
    getTranslations("InvitationAcceptance"),
  ]);
  if (!(await getServerUser())) {
    const login = locale === "pl" ? "/login" : `/${locale}/login`;
    redirect(
      `${login}?next=${encodeURIComponent(`/invitations/accept?token=${token ?? ""}`)}`,
    );
  }
  return (
    <AuthShell title={t("title")} description={t("description")}>
      <InvitationAcceptance token={token} />
    </AuthShell>
  );
}
