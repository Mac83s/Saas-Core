"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import {
  listBookingExtras,
  listBookingPrices,
  listParticipantCategories,
  type BookingExtra,
  type BookingPrice,
  type GroupSetup,
  type ParticipantCategory,
  type ResourceSetup,
  type ServiceSetup,
} from "@saas-core/api-client";

import { formatMoney } from "./money";

/** The company's price list as the panel holds it: one read, shared. */
export type PriceBook = {
  prices: BookingPrice[];
  /** How the amounts are read (`pricing.entry.amounts`). */
  amounts: "gross" | "net";
  categories: ParticipantCategory[];
  extras: BookingExtra[];
};

export type PriceSetup = {
  services: ServiceSetup[];
  groups: GroupSetup[];
  resources: ResourceSetup[];
};

export function usePriceBook(): {
  book?: PriceBook;
  failed: boolean;
  reload: () => Promise<void>;
} {
  const [book, setBook] = useState<PriceBook>();
  const [failed, setFailed] = useState(false);
  const reload = useCallback(async () => {
    try {
      const [list, categories, extras] = await Promise.all([
        listBookingPrices(),
        listParticipantCategories(),
        listBookingExtras(),
      ]);
      setBook({
        prices: list.items,
        amounts: list.amounts,
        categories,
        extras,
      });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void reload();
  }, [reload]);
  return { book, failed, reload };
}

export type Scope =
  `service:${string}` | `group:${string}` | `resource:${string}`;

export const scopeOf = (rule: BookingPrice): Scope | "" =>
  rule.service_id
    ? `service:${rule.service_id}`
    : rule.group_id
      ? `group:${rule.group_id}`
      : rule.resource_id
        ? `resource:${rule.resource_id}`
        : "";

/** „Za osobę za noc”: nothing for the unit itself, every person per night. */
export const isPerPersonPerUnit = (rule: BookingPrice) =>
  rule.basis === "per_time_unit" &&
  rule.amount_minor === 0 &&
  rule.included_people === 0 &&
  rule.extra_person_per_time_unit;

/** The prices that act on an offer: its own, its groups' and its units'. */
export function pricesOf(
  service: ServiceSetup,
  prices: BookingPrice[],
  resources: ResourceSetup[],
): BookingPrice[] {
  const units = new Set(
    resources
      .filter(
        (unit) =>
          service.resource_ids.includes(unit.id) ||
          (unit.group_id && service.group_ids.includes(unit.group_id)),
      )
      .map((unit) => unit.id),
  );
  return prices.filter(
    (rule) =>
      rule.service_id === service.id ||
      (service.time_model === "range" &&
        ((rule.group_id && service.group_ids.includes(rule.group_id)) ||
          (rule.resource_id && units.has(rule.resource_id)))),
  );
}

const asDay = (value: string) => new Date(`${value}T12:00:00`);
/** 0 = Monday … 6 = Sunday, as the API counts them; 2024-01-01 was a Monday. */
export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];
export const weekdayDate = (day: number) => new Date(2024, 0, 1 + day, 12);
export const clock = (value?: string | null) =>
  value ? value.slice(0, 5) : "";

/** A price in words: what it is called, what it prices, what it says. */
export function usePriceWords({ services, groups, resources }: PriceSetup) {
  const t = useTranslations("PriceList");
  const format = useFormatter();
  const locale = useLocale();

  /** Nights or days: the unit of the offers the price acts on. */
  const byDays = (rule: Pick<BookingPrice, "service_id" | "group_id">) => {
    const offers = services.filter(
      (service) =>
        service.time_model === "range" &&
        (rule.service_id
          ? service.id === rule.service_id
          : rule.group_id
            ? service.group_ids.includes(rule.group_id)
            : true),
    );
    return offers.length > 0 && offers.every((o) => o.range_unit === "day");
  };
  const when = (rule: BookingPrice) =>
    rule.starts_on && rule.ends_on
      ? format.dateTimeRange(asDay(rule.starts_on), asDay(rule.ends_on), {
          dateStyle: "medium",
        })
      : t("basePrice");
  const title = (rule: BookingPrice) => rule.name || when(rule);
  /** What narrows it within its dates: weekdays, hours. */
  const narrowed = (rule: BookingPrice) =>
    [
      rule.weekdays.length
        ? rule.weekdays
            .map((day) =>
              format.dateTime(weekdayDate(day), { weekday: "short" }),
            )
            .join(", ")
        : null,
      rule.local_from && rule.local_to
        ? `${clock(rule.local_from)}–${clock(rule.local_to)}`
        : null,
    ].filter((text): text is string => Boolean(text));
  const scope = (rule: BookingPrice) => {
    if (rule.service_id)
      return t("scopeService", {
        name: services.find((x) => x.id === rule.service_id)?.name ?? "—",
      });
    if (rule.group_id)
      return t("scopeGroup", {
        name: groups.find((x) => x.id === rule.group_id)?.name ?? "—",
      });
    return t("scopeUnit", {
      name: resources.find((x) => x.id === rule.resource_id)?.name ?? "—",
    });
  };
  const money = (rule: BookingPrice, minor: number) =>
    formatMoney(minor, rule.currency, locale);
  const unit = (rule: BookingPrice) => (byDays(rule) ? "day" : "night");
  /** „300,00 zł za noc”. */
  const amount = (rule: BookingPrice) =>
    isPerPersonPerUnit(rule)
      ? t("amountPerPersonPerUnit", {
          amount: money(rule, rule.extra_person_amount_minor ?? 0),
          unit: unit(rule),
        })
      : t(`amount_${rule.basis}` as "amount_per_booking", {
          amount: money(rule, rule.amount_minor),
          unit: unit(rule),
        });
  /** What it says beyond the amount: people, categories, discounts, tax. */
  const terms = (
    rule: BookingPrice,
    categories: { id: string; name: string }[],
  ) => {
    const special = isPerPersonPerUnit(rule);
    const perUnit = rule.extra_person_per_time_unit ? unit(rule) : "once";
    return [
      !special && rule.included_people !== null
        ? t("termIncluded", {
            count: rule.included_people,
            amount: money(rule, rule.extra_person_amount_minor ?? 0),
            unit: perUnit,
          })
        : null,
      ...rule.category_prices.map((line) =>
        t("termCategory", {
          name:
            categories.find((item) => item.id === line.category_id)?.name ??
            "—",
          amount: money(rule, line.amount_minor),
        }),
      ),
      ...rule.length_discounts.map((line) =>
        t("termDiscount", {
          count: line.min_length,
          percent: line.percent,
          unit: unit(rule),
        }),
      ),
      t("termVat", { code: rule.vat_code }),
    ].filter((text): text is string => Boolean(text));
  };
  return { amount, byDays, narrowed, scope, terms, title, unit, when };
}
