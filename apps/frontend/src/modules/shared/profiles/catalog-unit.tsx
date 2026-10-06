import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import type { CatalogUnitPage as CatalogUnitPayload } from "@saas-core/api-client";
import { stayAmount } from "@saas-core/site-blocks";

import { localizedPath } from "../../../marketing/seo";
import { CatalogUnitPhoto } from "./catalog-unit-photo";

/**
 * One unit a company lets — a cottage, a room, a kayak — as a page under
 * the company's catalogue card (ADR-072, slice 5h): what the company's own
 * booking form shows of it, and below it whatever books it (`children`: the
 * module that books draws its picker there). Rendered from a record, like
 * the card: the catalogue grows no page editor.
 */
export async function CatalogUnitPage({
  children,
  locale,
  page,
}: {
  children?: ReactNode;
  /** The page's language: the chrome's words and the dictionary's. */
  locale: string;
  page: CatalogUnitPayload;
}) {
  const t = await getTranslations("Catalog");
  const { company, unit } = page;
  const card = localizedPath(
    locale,
    `/katalog/${company.city_slug}/${company.slug}`,
  );
  const [cover, ...more] = unit.photos;
  const facts = [
    unit.town?.name,
    unit.capacity ? t("capacity", { count: unit.capacity }) : undefined,
    unit.from_price
      ? t("from", {
          per: unit.from_price.per,
          amount: stayAmount(unit.from_price, locale),
        })
      : undefined,
  ].filter(Boolean);

  return (
    <article className="space-y-8">
      <nav aria-label={t("breadcrumb")} lang={locale}>
        <ol className="text-muted-foreground flex flex-wrap gap-x-2 text-sm">
          <li>
            <a className="underline" href={localizedPath(locale, "/katalog")}>
              {t("title")}
            </a>
            <span aria-hidden="true"> ›</span>
          </li>
          <li>
            <a className="underline" href={card} lang={company.locale}>
              {company.display_name}
            </a>
            <span aria-hidden="true"> ›</span>
          </li>
          <li aria-current="page" lang={unit.locale}>
            {unit.name}
          </li>
        </ol>
      </nav>

      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">{unit.name}</h1>
        {facts.length > 0 && (
          <p className="text-muted-foreground" lang={locale}>
            {facts.join(" · ")}
          </p>
        )}
      </header>

      {cover && (
        <section aria-label={t("photosOf", { name: unit.name })} lang={locale}>
          <CatalogUnitPhoto
            alt={t("photoOf", { name: unit.name, number: 1 })}
            className="aspect-[4/3] h-auto w-full rounded-lg object-cover"
            eager
            locale={locale}
            photo={cover}
            sizes="(min-width: 768px) 46rem, 100vw"
          />
          {more.length > 0 && (
            <ul className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
              {more.map((photo, index) => (
                <li key={photo.id}>
                  <a href={photo.preview_url} rel="noopener" target="_blank">
                    <CatalogUnitPhoto
                      alt={t("photoOf", {
                        name: unit.name,
                        number: index + 2,
                      })}
                      className="aspect-[4/3] h-auto w-full rounded-md object-cover"
                      eager={index === 0}
                      locale={locale}
                      photo={photo}
                      sizes="(min-width: 640px) 11rem, 33vw"
                    />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {unit.description && (
        <section className="max-w-prose leading-relaxed whitespace-pre-line">
          {unit.description}
        </section>
      )}

      {unit.amenities.length > 0 && (
        // The dictionary's words, in the page's own language.
        <section lang={locale}>
          <h2 className="mb-2 text-sm font-medium">{t("amenities")}</h2>
          <ul className="flex flex-wrap gap-2">
            {unit.amenities.map((amenity) => (
              <li
                className="bg-muted rounded-full px-3 py-1 text-sm"
                key={amenity.key}
              >
                {amenity.label}
              </li>
            ))}
          </ul>
        </section>
      )}

      {children && (
        <section
          aria-labelledby="catalog-unit-booking"
          className="space-y-4"
          lang={locale}
        >
          <h2 className="text-lg font-medium" id="catalog-unit-booking">
            {t("checkDates")}
          </h2>
          {children}
        </section>
      )}

      <p className="text-sm" lang={locale}>
        {t.rich("offeredBy", {
          company: () => (
            <a className="underline" href={card} lang={company.locale}>
              {company.display_name}
            </a>
          ),
        })}
        {company.city ? ` · ${company.city}` : ""}
      </p>
    </article>
  );
}
