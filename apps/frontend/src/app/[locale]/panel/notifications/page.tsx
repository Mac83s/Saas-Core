import { getTranslations } from "next-intl/server";

import { getServerCurrentOrganization } from "#lib/server-auth";
import { NotificationsPanel } from "../../../../modules/shared/notifications";

export default async function NotificationsPage() {
  const [t, organization] = await Promise.all([
    getTranslations("Notifications"),
    getServerCurrentOrganization(),
  ]);
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-3xl text-muted-foreground">{t("description")}</p>
      </header>
      <NotificationsPanel canManageBilling={organization?.role === "owner"} />
    </main>
  );
}
