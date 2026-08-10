import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import {
  AuthShell,
  PasswordResetRequestForm,
} from "../../../../modules/core/identity";

export default async function PasswordResetPage() {
  const t = await getTranslations("Identity");
  return (
    <AuthShell
      title={t("resetRequestTitle")}
      description={t("resetRequestDescription")}
      footer={
        <Link className="text-primary hover:underline" href="/login">
          {t("backToLogin")}
        </Link>
      }
    >
      <PasswordResetRequestForm />
    </AuthShell>
  );
}
