import { getTranslations } from "next-intl/server";

import { CatalogSearch } from "../../../modules/shared/profiles";

export async function generateMetadata() {
  const t = await getTranslations("Catalog");
  return { title: t("title"), description: t("intro") };
}

export default async function CatalogPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations("Catalog");
  return (
    <main className="mx-auto min-h-screen w-full max-w-5xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-muted-foreground mt-2 mb-8">{t("intro")}</p>
      <CatalogSearch locale={locale} />
    </main>
  );
}
