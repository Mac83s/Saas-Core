import { getLocale, getTranslations } from "next-intl/server";

import { getPathname, Link } from "#i18n/navigation";

import { productHasCatalog } from "../../../marketing/content";

/**
 * A missing page of the product's site, under its own header and footer and
 * in the visitor's language, instead of the framework's bare English 404.
 * Rendered on every request to the group as the router's fallback, so it
 * fetches nothing.
 */
export default async function MarketingNotFound() {
  const t = await getTranslations("Marketing.notFound");
  const locale = await getLocale();
  return (
    <section className="mx-auto w-full max-w-3xl space-y-4 px-5 py-12 sm:py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-muted-foreground">{t("body")}</p>
      <div className="flex flex-wrap gap-4 text-sm font-medium">
        <Link href="/" className="underline underline-offset-4">
          {t("home")}
        </Link>
        {productHasCatalog && (
          <a
            href={getPathname({ href: "/katalog", locale })}
            className="underline underline-offset-4"
          >
            {t("catalog")}
          </a>
        )}
      </div>
    </section>
  );
}
