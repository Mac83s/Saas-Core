"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import {
  getPublicStayEnds,
  getPublicStayStarts,
  type CatalogUnitPage,
} from "@saas-core/api-client";

import { catalogFormHref } from "../profiles/catalog-links";
import { wallClock } from "./calendar-time";
import { StayDatePicker } from "./stay-date-picker";

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * „Sprawdź termin” on a unit's page in the catalogue (ADR-072, slice 5h):
 * the days and how many people come, read from the company's own booking
 * form — the free days from its API, a month at a time — and a link to that
 * form with what was chosen and the catalogue's `origin`. Nothing is booked
 * or priced here; the form asks the server about every choice again.
 */
export function CatalogStayPicker({
  booking,
  capacity,
  locale,
  offers,
  preset = {},
}: {
  booking: CatalogUnitPage["booking"];
  /** The most people the unit takes; null — nobody counts. */
  capacity: number | null;
  locale: string;
  offers: CatalogUnitPage["offers"];
  /** What the address of the page chose ahead: a search's days and guests. */
  preset?: { from?: string; to?: string; people?: string };
}) {
  const t = useTranslations("PublicBooking");
  const words = useTranslations("Catalog");
  const id = useId();
  const [offerId, setOfferId] = useState(offers[0]?.id ?? "");
  const offer = offers.find((item) => item.id === offerId) ?? offers[0];
  // The company's today: its calendar, not the browser's.
  const [today] = useState(() => wallClock(new Date(), booking.timezone).day);
  const [days, setDays] = useState(() => {
    // A day behind us, or an end before its start, is no choice.
    const start =
      DAY.test(preset.from ?? "") && (preset.from as string) >= today
        ? (preset.from as string)
        : "";
    const end =
      start && DAY.test(preset.to ?? "") && (preset.to as string) >= start
        ? (preset.to as string)
        : "";
    return { start, end };
  });
  // Kept as typed, so the field can be emptied on the way to another number.
  const [people, setPeople] = useState(
    /^[1-9]\d?$/.test(preset.people ?? "") ? String(preset.people) : "2",
  );
  if (!offer) return null;

  const unit = offer.range_unit === "day" ? "day" : "night";
  const target =
    offer.choice.kind === "group"
      ? { group_id: offer.choice.id }
      : { resource_id: offer.choice.id };
  const count = Math.max(0, Math.floor(Number(people)) || 0);
  const href = catalogFormHref(booking, {
    offer: offer.id,
    choice: offer.choice,
    from: days.start,
    // A departure without an arrival says nothing.
    to: days.start ? days.end : "",
    ...(count ? { people: count } : {}),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {offers.length > 1 ? (
          <label
            className="space-y-1 text-sm font-medium"
            htmlFor={`${id}-offer`}
          >
            <span className="block">{words("offer")}</span>
            <select
              className="border-input bg-background h-11 w-full rounded-md border px-3 text-sm font-normal"
              id={`${id}-offer`}
              onChange={(event) => {
                setOfferId(event.target.value);
                setDays({ start: "", end: "" });
              }}
              value={offer.id}
            >
              {offers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label
          className="space-y-1 text-sm font-medium"
          htmlFor={`${id}-people`}
        >
          <span className="block">{t("stayPeople")}</span>
          <input
            className="border-input bg-background h-11 w-full rounded-md border px-3 text-sm font-normal"
            id={`${id}-people`}
            inputMode="numeric"
            max={capacity ?? 99}
            min={1}
            onChange={(event) => setPeople(event.target.value)}
            type="number"
            value={people}
          />
        </label>
      </div>
      {booking.paused ? (
        <p className="text-muted-foreground text-sm" role="note">
          {words("paused")}
        </p>
      ) : (
        <StayDatePicker
          end={days.end}
          labels={{
            previousMonth: t("stayPreviousMonth"),
            nextMonth: t("stayNextMonth"),
            pickStart: t("stayPickStart", { unit }),
            pickEnd: t("stayPickEnd", { unit }),
            start: t(unit === "day" ? "stayFirstDay" : "stayArrival"),
            end: t(unit === "day" ? "stayLastDay" : "stayDeparture"),
            free: t("stayDayFree"),
            unavailable: t("stayDayUnavailable"),
            clear: t("stayClear"),
            loading: t("loadingTimes"),
            loadError: t("loadError"),
            noDays: t("stayNoDays"),
            length: (nights) => t("stayLength", { count: nights, unit }),
          }}
          lastDay={booking.last_day}
          loadEnds={(start) =>
            getPublicStayEnds(booking.form_slug, {
              service_id: offer.id,
              ...target,
              start,
            })
          }
          loadStarts={(from, to) =>
            getPublicStayStarts(booking.form_slug, {
              service_id: offer.id,
              ...target,
              from,
              to,
            })
          }
          locale={locale}
          months={2}
          onChange={(start, end) => setDays({ start, end })}
          searchKey={`${offer.id}:${offer.choice.kind}:${offer.choice.id}`}
          start={days.start}
          today={today}
          unit={unit}
        />
      )}
      <p>
        <a
          className="bg-primary text-primary-foreground inline-flex min-h-11 items-center justify-center rounded-lg px-5 text-sm font-medium"
          href={href}
          rel="nofollow"
        >
          {words(days.start && days.end ? "bookDates" : "book")}
        </a>
      </p>
    </div>
  );
}
