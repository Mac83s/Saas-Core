import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { getServerUser } from "#lib/server-auth";
import { AuthShell, LoginForm } from "../../../../modules/core/identity";

export default async function LoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ next?: string }>;
}) {
  const [{ locale }, { next }, t] = await Promise.all([
    params,
    searchParams,
    getTranslations("Identity"),
  ]);
  if (await getServerUser()) {
    redirect(locale === "pl" ? "/panel" : `/${locale}/panel`);
  }
  const returnTo =
    next?.startsWith("/") && !next.startsWith("//") ? next : "/panel";
  return (
    <AuthShell title={t("loginTitle")} description={t("loginDescription")}>
      <LoginForm returnTo={returnTo} />
    </AuthShell>
  );
}
