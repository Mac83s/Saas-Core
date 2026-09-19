import { getTranslations } from "next-intl/server";

import { getServerUser } from "#lib/server-auth";
import {
  PasswordCard,
  ProfileNameForm,
  SessionManager,
  TwoFactorCard,
} from "../../../../../modules/core/identity";

export default async function AccountSettingsPage() {
  const [t, user] = await Promise.all([
    getTranslations("AccountSettings"),
    getServerUser(),
  ]);
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </header>
      <div className="max-w-3xl space-y-7">
        <ProfileNameForm />
        {user ? <PasswordCard email={user.email} /> : null}
        <TwoFactorCard />
        <SessionManager />
      </div>
    </main>
  );
}
