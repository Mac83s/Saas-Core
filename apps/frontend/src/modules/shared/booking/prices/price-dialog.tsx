"use client";

import { useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { PlusIcon, Trash2Icon } from "lucide-react";

import {
  ApiProblemError,
  createBookingPrice,
  updateBookingPrice,
  type BookingPrice,
  type GroupSetup,
  type ParticipantCategory,
  type ResourceSetup,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { amountText, parseAmount } from "./money";
import {
  clock,
  isPerPersonPerUnit,
  scopeOf,
  WEEKDAYS,
  weekdayDate,
  type Scope,
} from "./price-book";

/** How a price is counted, as the form asks it: the API's bases, and „za
 *  osobę za noc” as a choice of its own (nothing for the unit, each person
 *  per night underneath). */
type Mode =
  | "per_booking"
  | "per_time_unit"
  | "per_person_per_time_unit"
  | "per_person"
  | "per_group";

export const VAT_CODES = ["23", "8", "5", "0", "zw", "np"] as const;
type VatCode = (typeof VAT_CODES)[number];

/** The server's own words for a refused price, else the screen's. */
export function refusal(error: unknown, fallback: string, stale: string) {
  if (!(error instanceof ApiProblemError)) return fallback;
  if (error.problem.code === "booking_version_conflict") return stale;
  const first = error.problem.errors?.[0]?.message;
  if (first) return first;
  return typeof error.problem.detail === "string" && error.problem.detail
    ? error.problem.detail
    : fallback;
}

/**
 * „Dodaj cenę” / „Edytuj cenę” (ADR-072 §6): what it prices, when it applies
 * — always, in a season, on some weekdays or hours — how it is counted, who
 * is in it and what the others add, and the discount for a longer stay.
 */
export function PriceDialog({
  amounts,
  categories,
  finalFocus,
  groups,
  item,
  onOpenChange,
  onSaved,
  resources,
  services,
}: {
  amounts: "gross" | "net";
  /** The categories a price may name: the active ones and those it has. */
  categories: ParticipantCategory[];
  finalFocus: HTMLElement | null;
  groups: GroupSetup[];
  item?: BookingPrice;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: BookingPrice, created: boolean) => void;
  resources: ResourceSetup[];
  services: ServiceSetup[];
}) {
  const t = useTranslations("PriceList");
  const common = useTranslations("Common");
  const format = useFormatter();
  const locale = useLocale();
  const special = item ? isPerPersonPerUnit(item) : false;
  const [name, setName] = useState(item?.name ?? "");
  const [scope, setScope] = useState<Scope | "">(
    item ? scopeOf(item) : services[0] ? `service:${services[0].id}` : "",
  );
  const [season, setSeason] = useState(Boolean(item?.starts_on));
  const [startsOn, setStartsOn] = useState(item?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(item?.ends_on ?? "");
  const [weekdays, setWeekdays] = useState<number[]>(item?.weekdays ?? []);
  const [localFrom, setLocalFrom] = useState(clock(item?.local_from));
  const [localTo, setLocalTo] = useState(clock(item?.local_to));
  const [mode, setMode] = useState<Mode | "">(
    item ? (special ? "per_person_per_time_unit" : item.basis) : "",
  );
  const [amount, setAmount] = useState(
    amountText(
      item
        ? special
          ? item.extra_person_amount_minor
          : item.amount_minor
        : null,
      locale,
    ),
  );
  const [vat, setVat] = useState<VatCode>(item?.vat_code ?? "23");
  const [included, setIncluded] = useState(
    item && !special && item.included_people !== null
      ? String(item.included_people)
      : "",
  );
  const [extraPerson, setExtraPerson] = useState(
    item && !special ? amountText(item.extra_person_amount_minor, locale) : "",
  );
  const [perUnit, setPerUnit] = useState(
    item ? item.extra_person_per_time_unit : true,
  );
  const [own, setOwn] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (item?.category_prices ?? []).map((line) => [
        line.category_id,
        amountText(line.amount_minor, locale),
      ]),
    ),
  );
  const [discounts, setDiscounts] = useState<
    { length: string; percent: string }[]
  >(() =>
    (item?.length_discounts ?? []).map((line) => ({
      length: String(line.min_length),
      percent: String(line.percent),
    })),
  );
  const [active, setActive] = useState(item?.active ?? true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const [kind, scopeId] = scope.split(":") as [
    "service" | "group" | "resource" | "",
    string | undefined,
  ];
  const offer =
    kind === "service" ? services.find((x) => x.id === scopeId) : undefined;
  // A visit has a set length: no price per night, but a price by the hour.
  const visit = offer?.time_model === "slot";
  const byDays = offer
    ? offer.range_unit === "day"
    : services.length > 0 &&
      services
        .filter((service) => service.time_model === "range")
        .every((service) => service.range_unit === "day");
  const unit = byDays ? "day" : "night";
  const modes: Mode[] = visit
    ? ["per_booking", "per_person", "per_group"]
    : [
        "per_time_unit",
        "per_person_per_time_unit",
        "per_booking",
        "per_person",
        "per_group",
      ];
  const chosen: Mode = modes.includes(mode as Mode) ? (mode as Mode) : modes[0];
  const everyPerson =
    chosen === "per_person" || chosen === "per_person_per_time_unit";
  const timed =
    chosen === "per_time_unit" || chosen === "per_person_per_time_unit";

  async function save() {
    if (!scope || !scopeId) return setProblem(t("scopeRequired"));
    if (season && (!startsOn || !endsOn)) return setProblem(t("datesRequired"));
    if (season && endsOn < startsOn) return setProblem(t("endBeforeStart"));
    const hours = visit && (localFrom || localTo);
    if (hours && (!localFrom || !localTo || localTo <= localFrom))
      return setProblem(t("hoursInvalid"));
    const value = parseAmount(amount);
    if (value === null) return setProblem(t("amountInvalid"));
    const people =
      everyPerson || included.trim() === "" ? null : Number(included);
    if (people !== null && (!Number.isInteger(people) || people < 0))
      return setProblem(t("includedInvalid"));
    const further = people === null ? null : parseAmount(extraPerson);
    if (people !== null && further === null)
      return setProblem(t("extraPersonRequired"));
    const categoryPrices: { category_id: string; amount_minor: number }[] = [];
    for (const category of categories) {
      const typed = (own[category.id] ?? "").trim();
      if (!typed) continue;
      const minor = parseAmount(typed);
      if (minor === null)
        return setProblem(t("categoryAmountInvalid", { name: category.name }));
      categoryPrices.push({ category_id: category.id, amount_minor: minor });
    }
    const lengthDiscounts = [];
    for (const line of timed ? discounts : []) {
      if (!line.length.trim() && !line.percent.trim()) continue;
      const length = Number(line.length);
      const percent = Number(line.percent);
      if (
        !Number.isInteger(length) ||
        length < 2 ||
        !Number.isInteger(percent) ||
        percent < 1 ||
        percent > 100
      )
        return setProblem(t("discountInvalid"));
      lengthDiscounts.push({ min_length: length, percent });
    }
    const perPersonPerUnit = chosen === "per_person_per_time_unit";
    const body = {
      name: name.trim(),
      service_id: kind === "service" ? scopeId : null,
      group_id: kind === "group" ? scopeId : null,
      resource_id: kind === "resource" ? scopeId : null,
      starts_on: season ? startsOn : null,
      ends_on: season ? endsOn : null,
      weekdays,
      local_from: hours ? localFrom : null,
      local_to: hours ? localTo : null,
      basis: perPersonPerUnit ? ("per_time_unit" as const) : chosen,
      // „Za osobę za noc”: the unit itself costs nothing, nobody is included
      // and each person pays the amount for every night.
      amount_minor: perPersonPerUnit ? 0 : value,
      vat_code: vat,
      included_people: perPersonPerUnit ? 0 : people,
      extra_person_amount_minor: perPersonPerUnit ? value : further,
      extra_person_per_time_unit: perPersonPerUnit
        ? true
        : chosen === "per_time_unit" && perUnit,
      category_prices: categoryPrices,
      length_discounts: lengthDiscounts,
      active,
    };
    setBusy(true);
    setProblem(undefined);
    try {
      onSaved(
        item
          ? await updateBookingPrice(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : await createBookingPrice(body, idempotencyKey),
        !item,
      );
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    } finally {
      setBusy(false);
    }
  }

  const entered = t(amounts === "net" ? "enteredNet" : "enteredGross");

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(item ? "editTitle" : "newTitle")}</DialogTitle>
            <DialogDescription>{t("dialogHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="price-scope">{t("appliesTo")}</FieldLabel>
              <NativeSelect
                id="price-scope"
                onChange={(event) => setScope(event.target.value as Scope)}
                value={scope}
              >
                {services.length ? (
                  <optgroup label={t("scopeOffers")}>
                    {services.map((service) => (
                      <option key={service.id} value={`service:${service.id}`}>
                        {service.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {groups.length ? (
                  <optgroup label={t("scopeGroups")}>
                    {groups.map((group) => (
                      <option key={group.id} value={`group:${group.id}`}>
                        {group.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {resources.length ? (
                  <optgroup label={t("scopeUnits")}>
                    {resources.map((thing) => (
                      <option key={thing.id} value={`resource:${thing.id}`}>
                        {thing.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="price-name">{t("name")}</FieldLabel>
              <Input
                autoComplete="off"
                id="price-name"
                maxLength={160}
                onChange={(event) => setName(event.target.value)}
                value={name}
              />
              <FieldDescription>{t("nameHint")}</FieldDescription>
            </Field>
          </div>
          <FieldSet>
            <FieldLegend>{t("legendWhen")}</FieldLegend>
            <div className="flex flex-wrap gap-x-6">
              {([false, true] as const).map((dated) => (
                <label
                  className="flex min-h-11 items-center gap-2 text-sm"
                  htmlFor={`price-when-${dated ? "season" : "base"}`}
                  key={String(dated)}
                >
                  <input
                    checked={season === dated}
                    className="size-4"
                    id={`price-when-${dated ? "season" : "base"}`}
                    name="price-when"
                    onChange={() => setSeason(dated)}
                    type="radio"
                  />
                  {t(dated ? "whenSeason" : "whenBase")}
                </label>
              ))}
            </div>
            {season ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="price-from">
                    {t("seasonFrom")}
                  </FieldLabel>
                  <Input
                    id="price-from"
                    onChange={(event) => setStartsOn(event.target.value)}
                    type="date"
                    value={startsOn}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="price-to">{t("seasonTo")}</FieldLabel>
                  <Input
                    id="price-to"
                    min={startsOn || undefined}
                    onChange={(event) => setEndsOn(event.target.value)}
                    type="date"
                    value={endsOn}
                  />
                </Field>
              </div>
            ) : null}
            <FieldSet>
              <FieldLegend variant="label">{t("weekdays")}</FieldLegend>
              <FieldDescription>{t("weekdaysHint")}</FieldDescription>
              <div className="flex flex-wrap gap-x-4">
                {WEEKDAYS.map((day) => (
                  <label
                    className="flex min-h-11 items-center gap-2 text-sm"
                    htmlFor={`price-weekday-${day}`}
                    key={day}
                  >
                    <input
                      checked={weekdays.includes(day)}
                      className="size-4"
                      id={`price-weekday-${day}`}
                      onChange={(event) =>
                        setWeekdays(
                          event.target.checked
                            ? [...weekdays, day].sort()
                            : weekdays.filter((other) => other !== day),
                        )
                      }
                      type="checkbox"
                    />
                    {format.dateTime(weekdayDate(day), { weekday: "short" })}
                  </label>
                ))}
              </div>
            </FieldSet>
            {visit ? (
              <FieldSet>
                <FieldLegend variant="label">{t("hours")}</FieldLegend>
                <FieldDescription>{t("hoursHint")}</FieldDescription>
                <div className="grid grid-cols-2 gap-4 sm:max-w-xs">
                  <Field>
                    <FieldLabel htmlFor="price-hour-from">
                      {t("hourFrom")}
                    </FieldLabel>
                    <Input
                      id="price-hour-from"
                      onChange={(event) => setLocalFrom(event.target.value)}
                      type="time"
                      value={localFrom}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="price-hour-to">
                      {t("hourTo")}
                    </FieldLabel>
                    <Input
                      id="price-hour-to"
                      onChange={(event) => setLocalTo(event.target.value)}
                      type="time"
                      value={localTo}
                    />
                  </Field>
                </div>
              </FieldSet>
            ) : null}
          </FieldSet>
          <FieldSet>
            <FieldLegend>{t("legendAmount")}</FieldLegend>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field>
                <FieldLabel htmlFor="price-basis">{t("basis")}</FieldLabel>
                <NativeSelect
                  id="price-basis"
                  onChange={(event) => setMode(event.target.value as Mode)}
                  value={chosen}
                >
                  {modes.map((option) => (
                    <option key={option} value={option}>
                      {t(`basis_${option}` as "basis_per_booking", { unit })}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="price-amount">
                  {t("amount", { entered })}
                </FieldLabel>
                <Input
                  autoComplete="off"
                  id="price-amount"
                  inputMode="decimal"
                  onChange={(event) => setAmount(event.target.value)}
                  value={amount}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="price-vat">{t("vat")}</FieldLabel>
                <NativeSelect
                  id="price-vat"
                  onChange={(event) => setVat(event.target.value as VatCode)}
                  value={vat}
                >
                  {VAT_CODES.map((code) => (
                    <option key={code} value={code}>
                      {t("vatCode", { code })}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
            <FieldDescription>
              {t(`basisHint_${chosen}` as "basisHint_per_booking", { unit })}
            </FieldDescription>
          </FieldSet>
          {everyPerson ? null : (
            <FieldSet>
              <FieldLegend>{t("legendPeople")}</FieldLegend>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="price-included">
                    {t("included")}
                  </FieldLabel>
                  <Input
                    id="price-included"
                    inputMode="numeric"
                    min={0}
                    onChange={(event) => setIncluded(event.target.value)}
                    type="number"
                    value={included}
                  />
                  <FieldDescription>{t("includedHint")}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="price-extra-person">
                    {t("extraPerson", { entered })}
                  </FieldLabel>
                  <Input
                    autoComplete="off"
                    disabled={included.trim() === ""}
                    id="price-extra-person"
                    inputMode="decimal"
                    onChange={(event) => setExtraPerson(event.target.value)}
                    value={extraPerson}
                  />
                  <FieldDescription>{t("extraPersonHint")}</FieldDescription>
                </Field>
              </div>
              {chosen === "per_time_unit" ? (
                <label
                  className="flex min-h-11 items-center gap-2 text-sm"
                  htmlFor="price-per-unit"
                >
                  <input
                    checked={perUnit}
                    className="size-4"
                    id="price-per-unit"
                    onChange={(event) => setPerUnit(event.target.checked)}
                    type="checkbox"
                  />
                  {t("perUnit", { unit })}
                </label>
              ) : null}
            </FieldSet>
          )}
          {categories.length ? (
            <FieldSet>
              <FieldLegend>{t("legendCategories")}</FieldLegend>
              <FieldDescription>
                {t(everyPerson ? "categoriesHintPerson" : "categoriesHint")}
              </FieldDescription>
              <div className="grid gap-4 sm:grid-cols-3">
                {categories.map((category) => (
                  <Field key={category.id}>
                    <FieldLabel htmlFor={`price-category-${category.id}`}>
                      {category.name}
                    </FieldLabel>
                    <Input
                      autoComplete="off"
                      id={`price-category-${category.id}`}
                      inputMode="decimal"
                      onChange={(event) =>
                        setOwn({ ...own, [category.id]: event.target.value })
                      }
                      value={own[category.id] ?? ""}
                    />
                  </Field>
                ))}
              </div>
            </FieldSet>
          ) : null}
          {timed ? (
            <FieldSet>
              <FieldLegend>{t("legendDiscounts")}</FieldLegend>
              <FieldDescription>
                {t("discountsHint", { unit })}
              </FieldDescription>
              {discounts.map((line, index) => (
                <div className="flex items-end gap-3" key={index}>
                  <Field>
                    <FieldLabel htmlFor={`price-discount-length-${index}`}>
                      {t("discountLength", { unit })}
                    </FieldLabel>
                    <Input
                      id={`price-discount-length-${index}`}
                      inputMode="numeric"
                      min={2}
                      onChange={(event) =>
                        setDiscounts(
                          discounts.map((other, at) =>
                            at === index
                              ? { ...other, length: event.target.value }
                              : other,
                          ),
                        )
                      }
                      type="number"
                      value={line.length}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor={`price-discount-percent-${index}`}>
                      {t("discountPercent")}
                    </FieldLabel>
                    <Input
                      id={`price-discount-percent-${index}`}
                      inputMode="numeric"
                      max={100}
                      min={1}
                      onChange={(event) =>
                        setDiscounts(
                          discounts.map((other, at) =>
                            at === index
                              ? { ...other, percent: event.target.value }
                              : other,
                          ),
                        )
                      }
                      type="number"
                      value={line.percent}
                    />
                  </Field>
                  <Button
                    aria-label={t("removeDiscount", { number: index + 1 })}
                    onClick={() =>
                      setDiscounts(discounts.filter((_, at) => at !== index))
                    }
                    size="icon"
                    type="button"
                    variant="outline"
                  >
                    <Trash2Icon aria-hidden="true" />
                  </Button>
                </div>
              ))}
              <div>
                <Button
                  onClick={() =>
                    setDiscounts([...discounts, { length: "", percent: "" }])
                  }
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <PlusIcon aria-hidden="true" />
                  {t("addDiscount")}
                </Button>
              </div>
            </FieldSet>
          ) : null}
          {item ? (
            <label
              className="flex min-h-11 items-center gap-2 text-sm"
              htmlFor="price-active"
            >
              <input
                checked={active}
                className="size-4"
                id="price-active"
                onChange={(event) => setActive(event.target.checked)}
                type="checkbox"
              />
              {t("priceActive")}
            </label>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy} type="submit">
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
