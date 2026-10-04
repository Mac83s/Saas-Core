"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  type FieldValues,
  type Path,
  type UseFormReturn,
  useWatch,
} from "react-hook-form";

import { getBookingSetup } from "@saas-core/api-client";
import { FieldDescription } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

type Offer = { id: string; name: string; online: boolean };

/**
 * Which of the company's offers booked from–to a stay block shows (ADR-072,
 * slice 5d): every offer on the form, or one of them. The block keeps the
 * offer's id; the list is the company's booking setup, read here. An
 * offer that is not booked online is named as such — the published page
 * shows nothing of it. Controlled, like the picture select: the options
 * arrive after the value.
 */
export function StayOfferSelect<TValues extends FieldValues>({
  form,
  id,
  invalid,
  name,
}: {
  form: UseFormReturn<TValues>;
  id: string;
  invalid: boolean;
  name: string;
}) {
  const t = useTranslations("Sites");
  // Unset — still asked for; an empty list — nothing booked from–to, or a
  // person who does not see the company's bookings.
  const [offers, setOffers] = useState<Offer[]>();
  const value =
    (useWatch({ control: form.control, name: name as Path<TValues> }) as
      string | undefined) ?? "";
  useEffect(() => {
    let current = true;
    getBookingSetup()
      .then((setup) =>
        setup.services
          .filter((item) => item.time_model === "range" && item.active)
          .map((item) => ({
            id: String(item.id),
            name: item.name,
            online: item.online,
          })),
      )
      .catch(() => [])
      .then((found) => {
        if (current) setOffers(found);
      });
    return () => {
      current = false;
    };
  }, []);
  return (
    <>
      <NativeSelect
        aria-invalid={invalid}
        id={id}
        {...form.register(name as never)}
        value={value}
      >
        <option value="">{t("stayOfferAll")}</option>
        {value && !offers?.some((offer) => offer.id === value) ? (
          <option value={value}>{t("stayOfferCurrent")}</option>
        ) : null}
        {offers?.map((offer) => (
          <option key={offer.id} value={offer.id}>
            {offer.online
              ? offer.name
              : t("stayOfferOffline", { name: offer.name })}
          </option>
        ))}
      </NativeSelect>
      {offers?.length === 0 ? (
        <FieldDescription>{t("stayOfferNone")}</FieldDescription>
      ) : null}
    </>
  );
}
