import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { routing } from "#i18n/routing";
import { productHasCatalog, productName } from "../../../../marketing/content";
import { CatalogSearch } from "../../../../modules/shared/profiles";
import { catalogListMetadata } from "../../../../modules/shared/profiles/catalog-seo";
import { readCatalogLocalesOnServer } from "../../../../modules/shared/profiles/catalog-server";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  // The catalogue is shared.profiles' public face; without it the address is
  // not a page of this product (and the 404 must not carry its title).
  if (!productHasCatalog) notFound();
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Catalog" });
  return catalogListMetadata({
    locale,
    locales: routing.locales,
    speaking: await readCatalogLocalesOnServer(),
    path: "/katalog",
    title: `${t("title")} — ${productName}`,
    description: t("intro"),
  });
}

export default async function CatalogPage({ params }: Props) {
  if (!productHasCatalog) notFound();
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
