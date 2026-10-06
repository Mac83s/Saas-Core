import type { Metadata } from "next";
import { cache } from "react";
import { notFound } from "next/navigation";

import { routing } from "#i18n/routing";
import { JsonLd } from "#components/json-ld";
import {
  productHasCatalog,
  productName,
} from "../../../../../../../marketing/content";
import { CatalogStayPicker } from "../../../../../../../modules/shared/booking/catalog-stay-picker";
import { CatalogUnitPage } from "../../../../../../../modules/shared/profiles";
import {
  catalogUnitJsonLd,
  catalogUnitMetadata,
} from "../../../../../../../modules/shared/profiles/catalog-seo";
import { readCatalogUnitOnServer } from "../../../../../../../modules/shared/profiles/catalog-server";

type Props = {
  params: Promise<{ locale: string; city: string; slug: string; unit: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

/** What a link to the page may choose ahead of the guest: a search's days
 *  and how many come. The page hands them on to the company's form. */
const PRESET = ["from", "to", "people"] as const;

// `generateMetadata` and the page both need the record, and the read is
// `no-store`, so without this every crawler hit would fetch it twice.
const load = cache(
  async (city: string, slug: string, unit: string, locale: string) => {
    if (!productHasCatalog) notFound();
    const page = await readCatalogUnitOnServer(city, slug, unit, locale);
    // The company left the catalogue, or its form no longer shows the unit.
    if (!page) notFound();
    return page;
  },
);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, city, slug, unit } = await params;
  const page = await load(city, slug, unit, locale);
  const town = page.unit.town?.name ?? page.company.city;
  return catalogUnitMetadata({
    page,
    locale,
    locales: routing.locales,
    path: `/katalog/${city}/${slug}/${unit}`,
    title: `${page.unit.name} — ${town} — ${page.company.display_name} — ${productName}`,
    // The unit's own words; one without a description is told by its place.
    description:
      page.unit.description.replace(/\s+/g, " ").trim().slice(0, 160) ||
      `${page.unit.name}, ${town} — ${page.company.display_name}`,
  });
}

export default async function CatalogUnitRoute({
  params,
  searchParams,
}: Props) {
  const { locale, city, slug, unit } = await params;
  const page = await load(city, slug, unit, locale);
  const query = await searchParams;
  const preset = Object.fromEntries(
    PRESET.flatMap((name) =>
      typeof query[name] === "string" ? [[name, query[name]]] : [],
    ),
  );
  return (
    // The company's own words in the company's language: the page says so
    // rather than letting the chrome's `lang` claim them (TL20).
    <section
      className="mx-auto w-full max-w-3xl px-5 py-12 sm:py-16"
      lang={page.unit.locale}
    >
      {/* A company's text: printed only through `JsonLd`. */}
      <JsonLd
        data={catalogUnitJsonLd({
          page,
          locales: routing.locales,
          cardPath: `/katalog/${city}/${slug}`,
          path: `/katalog/${city}/${slug}/${unit}`,
          locale,
        })}
      />
      <CatalogUnitPage locale={locale} page={page}>
        <CatalogStayPicker
          booking={page.booking}
          capacity={page.unit.capacity ?? null}
          locale={locale}
          offers={page.offers}
          preset={preset}
        />
      </CatalogUnitPage>
    </section>
  );
}
