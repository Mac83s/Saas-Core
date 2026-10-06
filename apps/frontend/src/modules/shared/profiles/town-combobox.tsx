"use client";

import { useTranslations } from "next-intl";

import type { CatalogDictionary } from "@saas-core/api-client";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";

export type Town = CatalogDictionary["cities"][number];

/** The open list shows this many; a town is found by typing, not by scrolling. */
const SHOWN = 50;

/** A name as it is typed: in any case, with or without Polish letters. */
function plain(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ł/giu, "l")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Two towns may share a name; the region tells them apart. */
function townLabel(town: Town): string {
  return town.voivodeship ? `${town.name}, ${town.voivodeship}` : town.name;
}

/**
 * A town answers the typed letters when its name, a word of it or its region
 * begins with them — „ol” is Olsztyn, not every town with „ol” inside, and
 * „olsztyn śl” is the Silesian one.
 */
function answers(town: Town, query: string): boolean {
  const asked = plain(query);
  const label = plain(townLabel(town));
  return (
    label.startsWith(asked) ||
    label.split(" ").some((word) => word.startsWith(asked))
  );
}

/**
 * The catalogue's town, picked by typing its name. The dictionary is every
 * town of Poland (ADR-053 §7), so a plain select would be a thousand rows.
 */
export function TownCombobox({
  id,
  towns,
  value,
  onChange,
  disabled = false,
  placeholder,
  describedBy,
}: {
  id: string;
  towns: Town[];
  /** The town's slug; "" for none. */
  value: string;
  onChange: (slug: string) => void;
  disabled?: boolean;
  placeholder: string;
  describedBy?: string;
}) {
  // The catalogue's own texts: the public search speaks every content language.
  const t = useTranslations("Catalog");
  const selected = value
    ? // A slug the dictionary has not answered for yet is shown as it is.
      (towns.find((town) => town.slug === value) ?? {
        slug: value,
        name: value,
        voivodeship: "",
      })
    : null;
  return (
    <Combobox
      disabled={disabled}
      filter={answers}
      isItemEqualToValue={(town: Town, other: Town) =>
        town?.slug === other?.slug
      }
      itemToStringLabel={townLabel}
      itemToStringValue={(town: Town) => town.slug}
      items={towns}
      limit={SHOWN}
      onValueChange={(town: Town | null) => onChange(town?.slug ?? "")}
      value={selected}
    >
      <ComboboxInput
        aria-describedby={describedBy}
        className="w-full"
        clearLabel={t("cityClear")}
        disabled={disabled}
        id={id}
        placeholder={placeholder}
        showClear={Boolean(selected) && !disabled}
        triggerLabel={t("cityShow")}
      />
      <ComboboxContent>
        <ComboboxEmpty>{t("cityEmpty")}</ComboboxEmpty>
        <ComboboxList>
          {(town: Town) => (
            <ComboboxItem key={town.slug} value={town}>
              <span>{town.name}</span>
              <span className="text-muted-foreground">{town.voivodeship}</span>
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
