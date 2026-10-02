import { getTranslations } from "next-intl/server";

import { CatalogSearch } from "../../../../modules/shared/profiles";

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
    // Inside the marketing layout: the catalogue is a page of the product's
    // site, under the same header, menu and footer, not a page of its own.
    <section className="mx-auto w-full max-w-6xl px-5 py-12 sm:py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-muted-foreground mt-2 mb-8">{t("intro")}</p>
      <CatalogSearch locale={locale} />
    </section>
  );
}
