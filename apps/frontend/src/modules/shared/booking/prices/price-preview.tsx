"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  getBookingQuote,
  type BookingQuote,
  type BookingQuoteLine,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { addDays, wallClock, zonedInstant } from "../calendar-time";
import { PanelQuote } from "./panel-quote";
import { ONE_PERSON, participantsOf, PartyFields, type Party } from "./party";
import { usePriceWords, type PriceBook, type PriceSetup } from "./price-book";
import { refusal } from "./price-dialog";

/**
 * „Jaka cena obowiązuje dnia …” (phase 3e): a date and a party, and the
 * server's quote for them — the price list asked whether or not the time
 * could be booked. Each line names the price it came from, so the company
 * sees which of its prices wins. Nothing is worked out here.
 */
export function PricePreview({
  book,
  services,
  setup,
  zone,
}: {
  book: PriceBook;
  /** The offers the preview asks about; one, and the offer is not asked. */
  services: ServiceSetup[];
  setup: PriceSetup;
  zone: string;
}) {
  const t = useTranslations("PriceList");
  const words = usePriceWords(setup);
  const [serviceId, setServiceId] = useState(services[0]?.id ?? "");
  const [target, setTarget] = useState("");
  const [date, setDate] = useState(() => wallClock(new Date(), zone).day);
  const [time, setTime] = useState("10:00");
  const [length, setLength] = useState("1");
  const [party, setParty] = useState<Party>(ONE_PERSON);
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{
    key: string;
    quote?: BookingQuote;
    problem?: string;
  }>();
  const offer =
    services.find((service) => service.id === serviceId) ?? services[0];
  const stay = offer?.time_model === "range";
  const byDays = offer?.range_unit === "day";
  const groups = setup.groups.filter(
    (group) => group.active && offer?.group_ids.includes(group.id),
  );
  const units = setup.resources.filter(
    (unit) =>
      unit.active &&
      ((unit.group_id && offer?.group_ids.includes(unit.group_id)) ||
        offer?.resource_ids.includes(unit.id)),
  );
  const categories = book.categories.filter((category) => category.active);
  // An answer is of the question as it was asked and of the price list as it
  // was then: a change to either takes the answer off the screen.
  const key = JSON.stringify([
    offer?.id,
    target,
    date,
    time,
    length,
    party,
    book.amounts,
    book.prices.map((rule) => [rule.id, rule.version]),
    book.extras.map((extra) => [extra.id, extra.version]),
  ]);
  const shown = answer?.key === key ? answer : undefined;
  const rules = new Map(book.prices.map((rule) => [rule.id, rule]));
  const source = (line: BookingQuoteLine) => {
    const rule =
      line.kind === "price" && line.price_rule_id
        ? rules.get(line.price_rule_id)
        : undefined;
    return rule
      ? t("fromPrice", { title: words.title(rule), scope: words.scope(rule) })
      : undefined;
  };

  async function ask() {
    if (!offer || !date) return;
    const nights = Math.max(1, Math.floor(Number(length) || 1));
    const [kind, id] = target.split(":");
    setBusy(true);
    try {
      const quote = await getBookingQuote({
        service_id: offer.id,
        ...(stay
          ? {
              start_date: date,
              end_date: addDays(date, byDays ? nights - 1 : nights),
              ...(kind === "group" ? { group_id: id } : {}),
              ...(kind === "unit" ? { resource_id: id } : {}),
            }
          : { starts_at: zonedInstant(date, time, zone).toISOString() }),
        participants: participantsOf(party),
        price_only: true,
      });
      setAnswer({ key, quote });
    } catch (error) {
      setAnswer({
        key,
        problem: refusal(error, t("previewFailed"), t("previewFailed")),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="price-preview-title"
      className="space-y-3 rounded-lg border bg-muted/30 p-4"
    >
      <div className="space-y-1">
        <h3 className="font-medium" id="price-preview-title">
          {t("previewTitle")}
        </h3>
        <p className="text-sm text-muted-foreground">{t("previewHint")}</p>
      </div>
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          {services.length > 1 ? (
            <Field className="col-span-2">
              <FieldLabel htmlFor="preview-offer">
                {t("previewOffer")}
              </FieldLabel>
              <NativeSelect
                id="preview-offer"
                onChange={(event) => {
                  setServiceId(event.target.value);
                  setTarget("");
                }}
                value={offer?.id ?? ""}
              >
                {services.map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          ) : null}
          <Field>
            <FieldLabel htmlFor="preview-date">
              {t(
                stay
                  ? byDays
                    ? "previewFirstDay"
                    : "previewArrival"
                  : "previewDate",
              )}
            </FieldLabel>
            <Input
              id="preview-date"
              onChange={(event) => setDate(event.target.value)}
              type="date"
              value={date}
            />
          </Field>
          {stay ? (
            <Field>
              <FieldLabel htmlFor="preview-length">
                {t(byDays ? "previewDays" : "previewNights")}
              </FieldLabel>
              <Input
                id="preview-length"
                inputMode="numeric"
                min={1}
                onChange={(event) => setLength(event.target.value)}
                type="number"
                value={length}
              />
            </Field>
          ) : (
            <Field>
              <FieldLabel htmlFor="preview-time">{t("previewTime")}</FieldLabel>
              <Input
                id="preview-time"
                onChange={(event) => setTime(event.target.value)}
                type="time"
                value={time}
              />
            </Field>
          )}
          {stay && groups.length + units.length > 1 ? (
            <Field className="col-span-2">
              <FieldLabel htmlFor="preview-unit">{t("previewUnit")}</FieldLabel>
              <NativeSelect
                id="preview-unit"
                onChange={(event) => setTarget(event.target.value)}
                value={target}
              >
                <option value="">{t("previewAnyUnit")}</option>
                {groups.map((group) => (
                  <option key={group.id} value={`group:${group.id}`}>
                    {t("previewGroup", { name: group.name })}
                  </option>
                ))}
                {units.map((unit) => (
                  <option key={unit.id} value={`unit:${unit.id}`}>
                    {unit.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          ) : null}
        </div>
        <PartyFields
          categories={categories}
          idPrefix="preview-party"
          onChange={setParty}
          value={party}
        />
        <Button
          disabled={busy || !offer || !date}
          type="submit"
          variant="outline"
        >
          {t("previewAsk")}
        </Button>
      </form>
      <div aria-live="polite" className="space-y-2">
        {shown?.problem ? (
          <p className="text-sm text-destructive">{shown.problem}</p>
        ) : null}
        {shown?.quote ? (
          shown.quote.lines.length || shown.quote.security_deposit_minor ? (
            <PanelQuote
              quote={shown.quote}
              source={source}
              title={t("previewAnswer")}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("previewNoPrice")}
            </p>
          )
        ) : null}
      </div>
    </section>
  );
}
