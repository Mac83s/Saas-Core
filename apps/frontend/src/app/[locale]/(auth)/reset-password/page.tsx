import { getTranslations } from "next-intl/server";

import {
  AuthShell,
  PasswordResetConfirmForm,
} from "../../../../modules/core/identity";

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const [{ token }, t] = await Promise.all([
    searchParams,
    getTranslations("Identity"),
  ]);
  return (
    <AuthShell
      title={t("resetConfirmTitle")}
      description={t("resetConfirmDescription")}
    >
      <PasswordResetConfirmForm token={token} />
    </AuthShell>
  );
}
