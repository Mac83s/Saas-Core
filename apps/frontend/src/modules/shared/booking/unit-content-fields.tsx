"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  readCatalogDictionary,
  type BookingSetup,
  type CatalogDictionary,
  type ResourceSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { ImageCropUpload } from "../media/crop";
import { PrivateMediaPreview } from "../sites/private-media-preview";

/** A unit as content (ADR-072, phase 5c): what a guest sees of it beyond its
 *  name — kept as the form holds it, numbers as typed. */
export type UnitContent = {
  shown: boolean;
  slug: string;
  town: string;
  latitude: string;
  longitude: string;
  /** „Pokaż dokładne położenie”: the map pins the unit's own point. */
  exact: boolean;
  amenities: string[];
  photos: string[];
};

type Options = BookingSetup["unit_options"];

/** The unit's content as its form starts with it. */
export function unitContentOf(unit: ResourceSetup | undefined): UnitContent {
  return {
    shown: unit?.public ?? false,
    slug: unit?.public_slug ?? "",
    town: unit?.city_slug ?? "",
    latitude: unit?.latitude == null ? "" : String(unit.latitude),
    longitude: unit?.longitude == null ? "" : String(unit.longitude),
    exact: unit?.show_exact_location ?? false,
    amenities: unit?.amenities ?? [],
    photos: unit?.photo_ids ?? [],
  };
}

/** The coordinates as the API takes them, or what is wrong with them. */
export function coordinatesOf(
  content: Pick<UnitContent, "latitude" | "longitude">,
):
  | { latitude: string | null; longitude: string | null }
  | "incomplete"
  | "range" {
  const latitude = content.latitude.trim().replace(",", ".");
  const longitude = content.longitude.trim().replace(",", ".");
  if (!latitude && !longitude) return { latitude: null, longitude: null };
  if (!latitude || !longitude) return "incomplete";
  const [north, east] = [Number(latitude), Number(longitude)];
  if (
    !Number.isFinite(north) ||
    !Number.isFinite(east) ||
    Math.abs(north) > 90 ||
    Math.abs(east) > 180
  )
    return "range";
  return { latitude: north.toFixed(6), longitude: east.toFixed(6) };
}

/**
 * The part of the unit's form that is its content: whether guests see it,
 * its address, town and coordinates, what it has, and its pictures in order —
 * the first is the cover.
 */
export function UnitContentFields({
  content,
  onChange,
  options,
}: {
  content: UnitContent;
  onChange: (next: UnitContent) => void;
  options: Options;
}) {
  const t = useTranslations("ServicesSetup");
  const locale = useLocale();
  const [dictionary, setDictionary] = useState<CatalogDictionary>();
  useEffect(() => {
    let mounted = true;
    void readCatalogDictionary()
      .then((value) => {
        if (mounted) setDictionary(value);
      })
      // Without the dictionary the town stays what it was.
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, []);
  const set = (change: Partial<UnitContent>) =>
    onChange({ ...content, ...change });
  const full = content.photos.length >= options.max_photos;
  return (
    <FieldSet>
      <FieldLegend variant="label">{t("unitContentTitle")}</FieldLegend>
      <Field>
        <label
          className="flex min-h-11 items-center gap-2 text-sm"
          htmlFor="resource-public"
        >
          <input
            checked={content.shown}
            className="size-4"
            id="resource-public"
            onChange={(event) => set({ shown: event.target.checked })}
            type="checkbox"
          />
          {t("unitPublic")}
        </label>
        <FieldDescription>{t("unitPublicHint")}</FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="resource-slug">{t("unitSlug")}</FieldLabel>
        <Input
          autoComplete="off"
          id="resource-slug"
          maxLength={80}
          onChange={(event) => set({ slug: event.target.value })}
          value={content.slug}
        />
        <FieldDescription>{t("unitSlugHint")}</FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="resource-town">{t("unitTown")}</FieldLabel>
        <NativeSelect
          id="resource-town"
          onChange={(event) => set({ town: event.target.value })}
          value={content.town}
        >
          <option value="">{t("unitTownNone")}</option>
          {/* The unit's own town, before the dictionary answers. */}
          {content.town &&
          !dictionary?.cities.some((city) => city.slug === content.town) ? (
            <option value={content.town}>{content.town}</option>
          ) : null}
          {dictionary?.cities.map((city) => (
            <option key={city.slug} value={city.slug}>
              {city.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="resource-latitude">
            {t("unitLatitude")}
          </FieldLabel>
          <Input
            autoComplete="off"
            id="resource-latitude"
            inputMode="decimal"
            onChange={(event) => set({ latitude: event.target.value })}
            placeholder="53.864500"
            value={content.latitude}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="resource-longitude">
            {t("unitLongitude")}
          </FieldLabel>
          <Input
            autoComplete="off"
            id="resource-longitude"
            inputMode="decimal"
            onChange={(event) => set({ longitude: event.target.value })}
            placeholder="21.305000"
            value={content.longitude}
          />
        </Field>
      </div>
      <p className="text-sm text-muted-foreground">
        {t("unitCoordinatesHint")}
      </p>
      <Field>
        <label
          className="flex min-h-11 items-center gap-2 text-sm"
          htmlFor="resource-exact-location"
        >
          <input
            aria-describedby="resource-exact-location-hint"
            checked={content.exact}
            className="size-4"
            id="resource-exact-location"
            onChange={(event) => set({ exact: event.target.checked })}
            type="checkbox"
          />
          {t("unitExactLocation")}
        </label>
        {/* What the switch publishes, said where it is switched. */}
        <FieldDescription id="resource-exact-location-hint">
          {t("unitExactLocationHint")}
        </FieldDescription>
      </Field>
      <FieldSet>
        <FieldLegend variant="label">{t("unitAmenities")}</FieldLegend>
        <div className="grid gap-x-4 sm:grid-cols-2">
          {options.amenities.map((amenity) => (
            <label
              className="flex min-h-11 items-center gap-2 text-sm"
              key={amenity.key}
            >
              <input
                checked={content.amenities.includes(amenity.key)}
                className="size-4"
                onChange={(event) =>
                  set({
                    amenities: event.target.checked
                      ? [...content.amenities, amenity.key]
                      : content.amenities.filter((key) => key !== amenity.key),
                  })
                }
                type="checkbox"
              />
              {amenity.label[locale] ?? amenity.label.en}
            </label>
          ))}
        </div>
      </FieldSet>
      <FieldSet>
        <FieldLegend variant="label">{t("unitPhotos")}</FieldLegend>
        <FieldDescription>
          {t("unitPhotosHint", { max: options.max_photos })}
        </FieldDescription>
        {content.photos.length ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {content.photos.map((id, index) => (
              <li className="space-y-2" key={id}>
                <div className="aspect-4/3 overflow-hidden rounded-lg border bg-muted [&_img]:size-full [&_img]:object-cover">
                  <PrivateMediaPreview
                    alt={t("unitPhotoAlt", { number: index + 1 })}
                    assetId={id}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {index ? (
                    <Button
                      aria-label={t("unitPhotoFirst", { number: index + 1 })}
                      onClick={() =>
                        set({
                          photos: [
                            id,
                            ...content.photos.filter((other) => other !== id),
                          ],
                        })
                      }
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {t("unitPhotoFirstShort")}
                    </Button>
                  ) : (
                    <span className="inline-flex h-8 items-center text-sm text-muted-foreground">
                      {t("unitPhotoCover")}
                    </span>
                  )}
                  <Button
                    aria-label={t("unitRemovePhoto", { number: index + 1 })}
                    onClick={() =>
                      set({
                        photos: content.photos.filter((other) => other !== id),
                      })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    {t("unitRemovePhotoShort")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        {full ? null : (
          <ImageCropUpload
            aspect={[4, 3]}
            label={t("unitAddPhoto")}
            onUploaded={(id) => set({ photos: [...content.photos, id] })}
          />
        )}
      </FieldSet>
    </FieldSet>
  );
}
