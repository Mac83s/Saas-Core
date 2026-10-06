import { redirect } from "next/navigation";

import { getServerUser } from "#lib/server-auth";
import { LoginScreen } from "../../../../modules/core/identity";

export default async function LoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ next?: string }>;
}) {
  const [{ locale }, { next }] = await Promise.all([params, searchParams]);
  if (await getServerUser()) {
    redirect(locale === "pl" ? "/panel" : `/${locale}/panel`);
  }
  const returnTo =
    next?.startsWith("/") && !next.startsWith("//") ? next : "/panel";
  return <LoginScreen returnTo={returnTo} />;
}
