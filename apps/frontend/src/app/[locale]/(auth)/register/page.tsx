import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { registrationHref } from "#lib/sign-up";
import { AuthShell, RegistrationForm } from "../../../../modules/core/identity";

export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  // A deployment nobody may sign up in serves no registration — except to
  // whoever comes with an invitation (`registrationHref`).
  if (registrationHref((await searchParams).next) === null) notFound();
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
