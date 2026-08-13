import { getTranslations } from "next-intl/server";

import { OrganizationPanel } from "../../../../modules/core/organizations";

export default async function TeamPage() {
  const t = await getTranslations("TeamPage");
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </header>
      <OrganizationPanel />
    </main>
  );
}
