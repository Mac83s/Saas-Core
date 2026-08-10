import { getTranslations } from "next-intl/server";

import { getServerUser } from "#lib/server-auth";
import { SessionManager } from "../../../modules/core/identity";
import { OrganizationPanel } from "../../../modules/core/organizations";

export default async function PanelPage() {
  const [user, t] = await Promise.all([
    getServerUser(),
    getTranslations("Panel"),
  ]);
  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-5 py-10">
      <section className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("account")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {t("greeting")}
        </h1>
        <p className="text-muted-foreground">
          {t("signedInAs", { email: user?.email ?? "" })}
        </p>
      </section>
      <OrganizationPanel />
      <div className="max-w-3xl">
        <SessionManager />
      </div>
    </main>
  );
}
