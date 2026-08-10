import { getTranslations } from "next-intl/server";

import { AuthShell, VerificationForm } from "../../../../modules/core/identity";

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const [{ token }, t] = await Promise.all([
    searchParams,
    getTranslations("Identity"),
  ]);
  return (
    <AuthShell title={t("verifyTitle")} description={t("verifyDescription")}>
      <VerificationForm token={token} />
    </AuthShell>
  );
}
