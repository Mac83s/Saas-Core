import { getLocale, getTranslations } from "next-intl/server";

import type { CatalogProfile } from "@saas-core/api-client";
import {
  approxAmount,
  conversionDay,
  stayAmount,
} from "@saas-core/site-blocks";

import { localizedPath } from "../../../marketing/seo";
import { catalogFormHref } from "./catalog-links";
import { CatalogUnitPhoto } from "./catalog-unit-photo";

/**
 * One catalogue page, rendered from a record rather than from blocks.
 *
 * ADR-053 §6: this is not a second publication path — sites keep theirs
 * untouched. The layout is a closed choice on the profile, so a company picks
 * a shape without the platform growing an editor it does not need.
 */
export async function CatalogProfilePage({
  profile,
}: {
  profile: CatalogProfile;
}) {
  const t = await getTranslations("Catalog");
  const locale = await getLocale();
  const cover = profile.layout === "cover";
  const compact = profile.layout === "compact";
  const booking = profile.booking;

  return (
    <article className="space-y-8">
      <header
        className={
          cover ? "bg-muted rounded-lg px-6 py-12 text-center" : "space-y-2"
        }
      >
        <h1 className="text-3xl font-semibold tracking-tight">
          {profile.display_name}
        </h1>
        {profile.headline && (
          <p className="text-muted-foreground text-lg">{profile.headline}</p>
        )}
        <p className="text-muted-foreground text-sm">
          {profile.city}
          {profile.voivodeship ? `, ${profile.voivodeship}` : ""}
        </p>
      </header>

      {profile.bio && !compact && (
        <section className="max-w-prose whitespace-pre-line leading-relaxed">
          {profile.bio}
        </section>
      )}

      {/* What a visitor can book here now, said by the company's own form
          (ADR-072, slice 5h). The link carries the catalogue's `origin`, so
          the booking says where it started. */}
      {booking && (
        <section
          aria-labelledby="catalog-booking"
          className="space-y-4"
          id="rezerwacja"
        >
          <h2 className="text-lg font-medium" id="catalog-booking">
            {t("onlineBooking")}
          </h2>
          {booking.units.length > 0 && (
            <ul className="grid gap-4 sm:grid-cols-2">
              {booking.units.map((unit) => (
                <li
                  className="overflow-hidden rounded-lg border"
                  key={unit.slug}
                >
                  {unit.photo && (
                    <CatalogUnitPhoto
                      alt={unit.name}
                      className="aspect-[4/3] h-auto w-full object-cover"
                      locale={locale}
                      photo={unit.photo}
                      sizes="(min-width: 640px) 22rem, 100vw"
                    />
                  )}
                  <div className="space-y-1 p-4">
                    <h3 className="font-medium">
                      <a
                        className="hover:underline"
                        href={localizedPath(
                          locale,
                          `/katalog/${profile.city_slug}/${profile.slug}/${unit.slug}`,
                        )}
                      >
                        {unit.name}
                      </a>
                    </h3>
                    <p className="text-muted-foreground text-sm">
                      {[
                        unit.town?.name,
                        unit.capacity
                          ? t("capacity", { count: unit.capacity })
                          : undefined,
                        unit.from_price
                          ? [
                              t("from", {
                                per: unit.from_price.per,
                                amount: stayAmount(unit.from_price, locale),
                              }),
                              // Roughly what it is in the reader's own
                              // currency (ADR-072, slice 5i).
                              approxAmount(
                                unit.from_price.gross_minor,
                                booking.conversion,
                                locale,
                              ),
                            ]
                              .filter(Boolean)
                              .join(" ")
                          : undefined,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    {unit.description && (
                      <p className="text-sm">{unit.description}</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {/* What the figures after „≈” are: once, under the units. */}
          {booking.conversion &&
            booking.units.some((unit) => unit.from_price) && (
              <p className="text-muted-foreground text-xs">
                {t("approxNote", {
                  bank: booking.conversion.bank,
                  date: conversionDay(booking.conversion, locale),
                  currency:
                    booking.units.find((unit) => unit.from_price)?.from_price
                      ?.currency ?? "",
                })}
              </p>
            )}
          <p>
            <a
              className="bg-primary text-primary-foreground inline-flex min-h-11 items-center justify-center rounded-lg px-5 text-sm font-medium"
              href={catalogFormHref(booking)}
              rel="nofollow"
            >
              {t("book")}
            </a>
          </p>
        </section>
      )}

      {profile.specializations.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-medium">{t("specializations")}</h2>
          <ul className="flex flex-wrap gap-2">
            {profile.specializations.map((key) => (
              <li className="bg-muted rounded-full px-3 py-1 text-sm" key={key}>
                {key}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-1">
        <h2 className="mb-2 text-sm font-medium">{t("contact")}</h2>
        {profile.contact_phone && (
          <p>
            <a className="underline" href={`tel:${profile.contact_phone}`}>
              {profile.contact_phone}
            </a>
          </p>
        )}
        {profile.contact_email && (
          <p>
            <a className="underline" href={`mailto:${profile.contact_email}`}>
              {profile.contact_email}
            </a>
          </p>
        )}
        {profile.contact_address && (
          <p className="text-muted-foreground">{profile.contact_address}</p>
        )}
      </section>

      {profile.links.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-medium">{t("links")}</h2>
          <ul className="space-y-1">
            {profile.links.map((link) => (
              <li key={String(link.url)}>
                <a
                  className="underline"
                  href={String(link.url)}
                  rel="noreferrer nofollow"
                  target="_blank"
                >
                  {String(link.label)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {profile.is_external && (
        <p>
          <a className="underline" href={profile.url} rel="noreferrer">
            {t("visitSite")}
          </a>
        </p>
      )}
    </article>
  );
}
