"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  CalendarCheckIcon,
  ExternalLinkIcon,
  LocateFixedIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";

import {
  readCatalogDictionary,
  searchCatalog,
  type CatalogDictionary,
  type CatalogItem,
  type CatalogPage,
  type CatalogSearch as CatalogQuery,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Slider } from "@saas-core/ui/components/slider";

import { localizedPath } from "../../../marketing/seo";
import { profileProblem } from "./problem";
import { TownCombobox } from "./town-combobox";

/** Typing pauses this long before the catalogue is asked. */
const TYPING_PAUSE_MS = 300;
/** "Near me" needs a radius; the slider starts here when it has none. */
const NEAR_ME_RADIUS_KM = 25;
const MAX_RADIUS_KM = 100;

/** The badge of a company a visitor can book online (ADR-072, slice 5h). */
const ONLINE_BOOKING = "online_booking";

type Point = { lat: number; lng: number };

function EntryCard({ item, locale }: { item: CatalogItem; locale: string }) {
  const t = useTranslations("Catalog");
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          <a
            className="hover:underline"
            // The platform's own page in the listing's language (TL20); a
            // company's site is its own address.
            href={item.is_external ? item.url : localizedPath(locale, item.url)}
            // An entry that leaves the platform opens in a new tab and says
            // so; one that stays does neither.
            rel={item.is_external ? "noreferrer" : undefined}
            target={item.is_external ? "_blank" : undefined}
          >
            {item.display_name}
            {item.is_external && (
              <ExternalLinkIcon
                aria-hidden="true"
                className="ml-1 inline size-3.5 align-baseline"
              />
            )}
          </a>
        </CardTitle>
        <CardDescription lang={item.locale}>{item.headline}</CardDescription>
      </CardHeader>
      <CardContent className="text-muted-foreground space-y-2 text-sm">
        <p>
          {item.city}
          {item.distance_km !== null && item.distance_km !== undefined && (
            <> · {t("km", { km: Math.round(item.distance_km) })}</>
          )}
        </p>
        {/* Always the platform's own page of the company — also when its
            name leads to the company's site: the booking starts here, so it
            says the catalogue sent the guest. (`?.`: a page that loaded
            while the backend behind it was still the older one.) */}
        {item.badges?.includes(ONLINE_BOOKING) && (
          <p>
            <a
              className="text-foreground inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium hover:underline"
              href={`${localizedPath(locale, `/katalog/${item.city_slug}/${item.slug}`)}#rezerwacja`}
            >
              <CalendarCheckIcon aria-hidden="true" className="size-3.5" />
              {t("onlineBooking")}
            </a>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Entries({ items, locale }: { items: CatalogItem[]; locale: string }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <li key={`${item.city_slug}/${item.slug}`}>
          <EntryCard item={item} locale={locale} />
        </li>
      ))}
    </ul>
  );
}

/**
 * The public listing. Filters are dictionary values only — the API refuses
 * anything else (ADR-053 §7), so the form offers exactly what it accepts.
 * Entries that contain the words come first; entries that fit them by meaning
 * come as "Podobne" when there are none, and as "Może też" below them
 * otherwise (ADR-064 §8).
 */
export function CatalogSearch({
  initialCity = "",
  locale,
}: {
  initialCity?: string;
  locale: string;
}) {
  const t = useTranslations("Catalog");
  const [dictionary, setDictionary] = useState<CatalogDictionary | null>(null);
  const [city, setCity] = useState(initialCity);
  const [category, setCategory] = useState("");
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  const [radius, setRadius] = useState(0);
  const [bookable, setBookable] = useState(false);
  const [near, setNear] = useState<Point | null>(null);
  const [locating, setLocating] = useState(false);
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await readCatalogDictionary();
        if (!cancelled) setDictionary(loaded);
      } catch (caught) {
        if (!cancelled) setError(profileProblem(caught, t("loadFailed")));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    const pause = setTimeout(() => setQuery(typed), TYPING_PAUSE_MS);
    return () => clearTimeout(pause);
  }, [typed]);

  // The point leaves the browser only in this request; the API neither stores
  // nor logs it (ADR-064 §7).
  // Headlines in the page's language where the card is whole in it (TL20).
  const search: CatalogQuery = near
    ? {
        category,
        q: query,
        lat: near.lat,
        lng: near.lng,
        radius_km: radius,
        locale,
        ...(bookable ? { badge: ONLINE_BOOKING } : {}),
      }
    : {
        city,
        category,
        q: query,
        ...(city && radius ? { radius_km: radius } : {}),
        locale,
        ...(bookable ? { badge: ONLINE_BOOKING } : {}),
      };
  const searchKey = JSON.stringify(search);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const found = await searchCatalog(
          JSON.parse(searchKey) as CatalogQuery,
        );
        if (!cancelled) {
          setPage(found);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(profileProblem(caught, t("loadFailed")));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchKey, t]);

  function locate() {
    if (!("geolocation" in navigator)) {
      setError(t("locationFailed"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        setNear({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
        setRadius((current) => current || NEAR_ME_RADIUS_KM);
        setError(null);
      },
      () => {
        setLocating(false);
        setError(t("locationFailed"));
      },
      { maximumAge: 600_000, timeout: 10_000 },
    );
  }

  const distanceActive = near !== null || city !== "";
  const items = page?.items ?? [];
  const similar = page?.similar ?? [];

  return (
    <div className="space-y-8">
      <form
        className="grid gap-4 sm:grid-cols-3"
        onSubmit={(event) => event.preventDefault()}
        role="search"
      >
        <Field>
          <FieldLabel htmlFor="catalog-q">{t("query")}</FieldLabel>
          <Input
            id="catalog-q"
            onChange={(event) => setTyped(event.target.value)}
            placeholder={t("queryPlaceholder")}
            type="search"
            value={typed}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="catalog-city">{t("city")}</FieldLabel>
          {near ? (
            <div className="flex h-9 items-center justify-between gap-2 rounded-md border px-3 text-sm">
              <span className="flex items-center gap-2">
                <LocateFixedIcon aria-hidden="true" className="size-4" />
                {t("nearMeActive")}
              </span>
              <Button
                aria-label={t("nearMeClear")}
                onClick={() => {
                  setNear(null);
                  setRadius(0);
                }}
                size="icon"
                variant="ghost"
              >
                <XIcon aria-hidden="true" />
              </Button>
            </div>
          ) : (
            <TownCombobox
              id="catalog-city"
              onChange={setCity}
              placeholder={t("anyCity")}
              towns={dictionary?.cities ?? []}
              value={city}
            />
          )}
        </Field>
        <Field>
          <FieldLabel htmlFor="catalog-category">{t("category")}</FieldLabel>
          <NativeSelect
            id="catalog-category"
            onChange={(event) => setCategory(event.target.value)}
            value={category}
          >
            <option value="">{t("anyCategory")}</option>
            {(dictionary?.categories ?? []).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.labels[locale] ?? entry.labels.pl ?? entry.key}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="space-y-2 sm:col-span-2">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="font-medium" id="catalog-distance">
              {t("distance")}
            </span>
            <span className="text-muted-foreground" aria-live="polite">
              {!distanceActive
                ? t("distanceHint")
                : radius === 0
                  ? t("onlyCity")
                  : t("withinKm", { km: radius })}
            </span>
          </div>
          <Slider
            aria-labelledby="catalog-distance"
            disabled={!distanceActive}
            max={MAX_RADIUS_KM}
            min={near ? 5 : 0}
            onValueChange={(value) =>
              setRadius(Array.isArray(value) ? (value[0] ?? 0) : value)
            }
            step={5}
            value={radius}
          />
        </div>
        <div className="flex flex-col justify-end gap-1">
          <Button
            disabled={locating}
            onClick={locate}
            type="button"
            variant="outline"
          >
            <LocateFixedIcon aria-hidden="true" />
            {locating ? t("locating") : t("nearMe")}
          </Button>
          <p className="text-muted-foreground text-xs">
            {t("locationPrivacy")}
          </p>
        </div>
        {/* Only where the product's catalogue has the badge: a product
            that takes no bookings offers no such filter. */}
        {dictionary?.badges?.includes(ONLINE_BOOKING) && (
          <label
            className="flex min-h-11 items-center gap-2 text-sm font-medium sm:col-span-3"
            htmlFor="catalog-bookable"
          >
            <input
              checked={bookable}
              className="size-4"
              id="catalog-bookable"
              onChange={(event) => setBookable(event.target.checked)}
              type="checkbox"
            />
            {t("onlineBookingOnly")}
          </label>
        )}
      </form>

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      {page && page.total === 0 && similar.length === 0 && (
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <SearchIcon aria-hidden="true" className="size-4" />
          {t("empty")}
        </p>
      )}

      {items.length === 0 && similar.length > 0 ? (
        <section aria-labelledby="catalog-similar" className="space-y-4">
          <h2 className="text-lg font-medium" id="catalog-similar">
            {t("noExact", { query })}
          </h2>
          <Entries items={similar} locale={locale} />
        </section>
      ) : (
        <>
          <Entries items={items} locale={locale} />
          {page && page.total > items.length && (
            <Button
              onClick={() => {
                void searchCatalog({ ...search, page: page.page + 1 }).then(
                  (next) =>
                    setPage({
                      ...page,
                      page: next.page,
                      items: [...items, ...next.items],
                    }),
                );
              }}
              variant="outline"
            >
              {t("more")}
            </Button>
          )}
          {similar.length > 0 && (
            <section aria-labelledby="catalog-may-also" className="space-y-4">
              <h2 className="text-lg font-medium" id="catalog-may-also">
                {t("mayAlso")}
              </h2>
              <Entries items={similar} locale={locale} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
