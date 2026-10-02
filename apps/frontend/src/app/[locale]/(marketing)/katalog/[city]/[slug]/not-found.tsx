import { getLocale, getTranslations } from "next-intl/server";

import { getPathname } from "#i18n/navigation";

/** A withdrawn or erased company: say so, and lead back to the catalogue. */
export default async function CatalogEntryNotFound() {
  const t = await getTranslations("Catalog.gone");
  const locale = await getLocale();
  return (
    <section className="mx-auto w-full max-w-3xl space-y-4 px-5 py-12 sm:py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-muted-foreground">{t("body")}</p>
      {/* A full page load, like the menu link: the catalogue's geolocation
          policy comes with its own response (marketing/navigation.ts). */}
      <a
        href={getPathname({ href: "/katalog", locale })}
        className="text-sm font-medium underline underline-offset-4"
      >
        {t("back")}
      </a>
    </section>
  );
}
