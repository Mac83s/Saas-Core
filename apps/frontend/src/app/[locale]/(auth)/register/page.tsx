import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { AuthShell, RegistrationForm } from "../../../../modules/core/identity";

export default async function RegisterPage() {
  const t = await getTranslations("Identity");
  return (
    <AuthShell
      title={t("registerTitle")}
      description={t("registerDescription")}
      footer={
        <Link className="text-primary hover:underline" href="/verify-email">
          {t("alreadyHaveMessage")}
        </Link>
      }
    >
      <RegistrationForm />
    </AuthShell>
  );
}
