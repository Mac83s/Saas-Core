"use client";

import { useLocale, useTranslations } from "next-intl";

import type { BookingExtra, ParticipantCategory } from "@saas-core/api-client";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { formatMoney } from "./money";

/** Who comes: standard people and so many of each category. */
export type Party = { people: number; categories: Record<string, number> };

export const ONE_PERSON: Party = { people: 1, categories: {} };

/** The party as the API takes it; nobody of a kind is left out. */
export function participantsOf(party: Party) {
  return [
    ...(party.people > 0 ? [{ category_id: null, count: party.people }] : []),
    ...Object.entries(party.categories)
      .filter(([, count]) => count > 0)
      .map(([category_id, count]) => ({ category_id, count })),
  ];
}

/** The optional extras picked, as the API takes them. */
export function extrasOf(picked: Record<string, number>) {
  return Object.entries(picked)
    .filter(([, quantity]) => quantity > 0)
    .map(([extra_id, quantity]) => ({ extra_id, quantity }));
}

const count = (value: string) =>
  Math.max(0, Math.min(1000, Math.floor(Number(value) || 0)));

/** „Osoby” and one number for each category the company prices. */
export function PartyFields({
  categories,
  idPrefix,
  onChange,
  value,
}: {
  /** The active categories; none, and only the people are asked about. */
  categories: ParticipantCategory[];
  idPrefix: string;
  onChange: (next: Party) => void;
  value: Party;
}) {
  const t = useTranslations("PriceList");
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
      <Field>
        <FieldLabel htmlFor={`${idPrefix}-people`}>{t("people")}</FieldLabel>
        <Input
          id={`${idPrefix}-people`}
          inputMode="numeric"
          min={0}
          onChange={(event) =>
            onChange({ ...value, people: count(event.target.value) })
          }
          type="number"
          value={value.people}
        />
      </Field>
      {categories.map((category) => (
        <Field key={category.id}>
          <FieldLabel htmlFor={`${idPrefix}-${category.id}`}>
            {category.name}
          </FieldLabel>
          <Input
            id={`${idPrefix}-${category.id}`}
            inputMode="numeric"
            min={0}
            onChange={(event) =>
              onChange({
                ...value,
                categories: {
                  ...value.categories,
                  [category.id]: count(event.target.value),
                },
              })
            }
            type="number"
            value={value.categories[category.id] ?? 0}
          />
        </Field>
      ))}
    </div>
  );
}

/** The extras a booking may take: a checkbox, or how many of it. */
export function ExtrasPicker({
  extras,
  idPrefix,
  onChange,
  value,
}: {
  /** The offer's active extras the customer picks; mandatory ones are the server's. */
  extras: BookingExtra[];
  idPrefix: string;
  onChange: (next: Record<string, number>) => void;
  value: Record<string, number>;
}) {
  const t = useTranslations("PriceList");
  const locale = useLocale();
  return (
    <div className="grid gap-1">
      {extras.map((extra) => {
        const label = t("extraOption", {
          name: extra.name,
          amount: formatMoney(extra.amount_minor, extra.currency, locale),
          basis: extra.basis,
        });
        const id = `${idPrefix}-${extra.id}`;
        return extra.max_quantity > 1 ? (
          <label
            className="flex min-h-11 items-center justify-between gap-3 text-sm"
            htmlFor={id}
            key={extra.id}
          >
            <span className="min-w-0 wrap-anywhere">{label}</span>
            {/* The select's own box is this narrow: its arrow stays inside. */}
            <span className="w-20 shrink-0">
              <NativeSelect
                aria-label={t("extraQuantity", { name: extra.name })}
                id={id}
                onChange={(event) =>
                  onChange({ ...value, [extra.id]: Number(event.target.value) })
                }
                value={value[extra.id] ?? 0}
              >
                {Array.from({ length: extra.max_quantity + 1 }, (_, number) => (
                  <option key={number} value={number}>
                    {number}
                  </option>
                ))}
              </NativeSelect>
            </span>
          </label>
        ) : (
          <label
            className="flex min-h-11 items-center gap-2 text-sm"
            htmlFor={id}
            key={extra.id}
          >
            <input
              checked={Boolean(value[extra.id])}
              className="size-4 shrink-0"
              id={id}
              onChange={(event) =>
                onChange({ ...value, [extra.id]: event.target.checked ? 1 : 0 })
              }
              type="checkbox"
            />
            <span className="min-w-0 wrap-anywhere">{label}</span>
          </label>
        );
      })}
    </div>
  );
}
