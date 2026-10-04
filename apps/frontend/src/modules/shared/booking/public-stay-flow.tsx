"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  createPublicStay,
  getPublicStayEnds,
  getPublicStayPlan,
  getPublicStayStarts,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicConsents,
  type BookingPublicQuote,
  type BookingPublicStayPlan,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { addDays, formatDay, wallClock } from "./calendar-time";
import {
  BookedCard,
  ContactFields,
  type ContactValues,
  contactIssues,
  contactShape,
  DocumentBoxes,
  ExtrasPicker,
  type MarketingBox,
  otherLanguages,
  pickedExtras,
  refusalOf,
  ticked,
  UnitCover,
  UnitFacts,
  UnitGallery,
  type UnitContent,
} from "./public-booking-parts";
import { QuoteSummary } from "./quote-summary";

type Documents = BookingPublicConsents["documents"];
type Offer = NonNullable<BookingPublicCatalog["stays"]>[number];

/** One search of arrival days: what the server answers at once (ADR-072,
 *  phase 5a — its public window is 92 days). */
const WINDOW_DAYS = 91;
/** What the offer lets a guest choose: a group — the server picks the unit
 *  (ADR-072 §3) — or a unit listed by itself. */
type Choice = UnitContent & {
  key: string;
  target: { group_id: string } | { resource_id: string };
  name: string;
  description: string;
  capacity: number | null;
};

function choicesOf(offer: Offer | undefined): Choice[] {
  if (!offer) return [];
  return [
    ...offer.groups.map((group) => ({
      ...group,
      key: `group:${group.id}`,
      target: { group_id: String(group.id) },
    })),
    ...offer.units.map((unit) => ({
      ...unit,
      key: `unit:${unit.id}`,
      target: { resource_id: String(unit.id) },
    })),
  ];
}

/**
 * The public form of an offer booked from–to — nights or days (ADR-072,
 * phase 5b): what is booked, who comes, the days, the extras, the price the
 * server works out, the customer and the company's documents. Every amount
 * and every free day is the server's; the form only asks.
 */
export function PublicStayFlow({
  catalog,
  documents,
  marketing,
  offerId,
  onDocuments,
  onElsewhere,
  onOffer,
  publicSlug,
}: {
  catalog: BookingPublicCatalog;
  documents: Documents;
  /** The marketing consent the company asks for, ticked or not. */
  marketing?: MarketingBox;
  /** The stay offer chosen in „Usługa”. */
  offerId: string;
  /** Other documents are in force by now: the form shows those. */
  onDocuments: (documents: Documents) => void;
  /** The booking terms have no text in this language by now: the languages
   *  to offer instead. */
  onElsewhere: (locales: string[]) => void;
  /** Another offer was chosen — a stay or a visit. */
  onOffer: (id: string) => void;
  publicSlug: string;
}) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const stays = useMemo(() => catalog.stays ?? [], [catalog.stays]);
  const offer = stays.find((item) => String(item.id) === offerId);
  const choices = useMemo(() => choicesOf(offer), [offer]);
  const unit = offer?.range_unit === "day" ? "day" : "night";
  const contact = catalog.online.contact;
  // What is booked: the only choice by itself, otherwise the guest's pick.
  const [chosen, setChosen] = useState("");
  const choice =
    choices.length === 1
      ? choices[0]
      : choices.find((item) => item.key === chosen);
  // Who comes: standard people, and so many of each of the company's
  // categories („Dziecko”, „Pies”).
  // Counts are kept as typed, so a field can be emptied on the way to another
  // number; what is asked of the server are the whole numbers in them.
  const categories = catalog.participant_categories ?? [];
  const [people, setPeople] = useState("2");
  const [others, setOthers] = useState<Record<string, string>>({});
  const participants = useMemo(() => {
    const count = (typed: string) =>
      Math.max(0, Math.floor(Number(typed)) || 0);
    return [
      ...(count(people) ? [{ category_id: null, count: count(people) }] : []),
      ...Object.entries(others)
        .filter(([, typed]) => count(typed))
        .map(([category_id, typed]) => ({ category_id, count: count(typed) })),
    ];
  }, [others, people]);
  // The days: the window searched, the arrival days it found, the arrival
  // chosen, the departures it allows and the one chosen. An unset list is
  // one still being asked for.
  const [today] = useState(() => wallClock(new Date(), catalog.timezone).day);
  const lastDay = catalog.online.period_last_day ?? addDays(today, WINDOW_DAYS);
  const [from, setFrom] = useState(today);
  // The window one search covers: from `from`, never past the last day.
  const until = [addDays(from, WINDOW_DAYS), lastDay].sort()[0];
  const [starts, setStarts] = useState<string[]>();
  const [start, setStart] = useState("");
  const [ends, setEnds] = useState<string[]>();
  const [end, setEnd] = useState("");
  const [picked, setPicked] = useState<Record<string, number>>({});
  const extras = useMemo(() => pickedExtras(picked), [picked]);
  const options = (catalog.extras ?? []).filter(
    (item) => String(item.service_id) === offerId && !item.mandatory,
  );
  // The stay as the server plans and prices it for what is chosen now; an
  // answer for an earlier choice is not shown.
  const asked = useMemo(
    () =>
      choice && start && end
        ? {
            service_id: offerId,
            ...choice.target,
            start_date: start,
            end_date: end,
            // Nobody named: the server counts one standard person.
            ...(participants.length ? { participants } : {}),
            ...(extras.length ? { extras } : {}),
          }
        : undefined,
    [choice, end, extras, offerId, participants, start],
  );
  const askedKey = asked ? JSON.stringify(asked) : "";
  const [planned, setPlanned] = useState<{
    key: string;
    plan?: BookingPublicStayPlan;
    refusal?: string;
  }>();
  const plan = planned?.key === askedKey ? planned.plan : undefined;
  const refusal = planned?.key === askedKey ? planned.refusal : undefined;
  // Counts the times a throttled question was put again.
  const [attempt, setAttempt] = useState(0);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [tried, setTried] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [booked, setBooked] = useState<BookingPublicAppointment>();
  const schema = useMemo(
    () => z.object(contactShape(t)).superRefine(contactIssues(contact, t)),
    [contact, t],
  );
  const form = useForm<ContactValues>({
    resolver: zodResolver(schema),
    defaultValues: { display_name: "", email: "", phone: "", notes: "" },
  });
  const targetKey = choice?.key ?? "";

  // Each answer is dropped once the guest has moved on to another choice.
  useEffect(() => {
    if (!choice) return;
    let current = true;
    getPublicStayStarts(publicSlug, {
      service_id: offerId,
      ...choice.target,
      from,
      to: until,
    })
      .then((days) => {
        if (current) setStarts(days);
      })
      .catch(() => {
        if (!current) return;
        setStarts([]);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
    // `choice` is named by its key: the same pick must not search twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, offerId, publicSlug, t, targetKey, until]);
  useEffect(() => {
    if (!choice || !start) return;
    let current = true;
    getPublicStayEnds(publicSlug, {
      service_id: offerId,
      ...choice.target,
      start,
    })
      .then((days) => {
        if (current) setEnds(days);
      })
      .catch(() => {
        if (!current) return;
        setEnds([]);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offerId, publicSlug, start, t, targetKey]);
  useEffect(() => {
    if (!asked) return;
    let current = true;
    let again: ReturnType<typeof setTimeout> | undefined;
    // A short pause: a count typed digit by digit asks once.
    const timer = setTimeout(() => {
      getPublicStayPlan(publicSlug, { ...asked, locale })
        .then((value) => {
          if (current) setPlanned({ key: askedKey, plan: value });
        })
        .catch((error: unknown) => {
          if (!current) return;
          const reason = refusalOf(error);
          setPlanned({ key: askedKey, refusal: reason });
          // Too many questions at once is nothing about the dates: the same
          // one is put again in a moment, as the guest was told.
          if (reason === "throttled")
            again = setTimeout(() => setAttempt((count) => count + 1), 5000);
        });
    }, 300);
    return () => {
      current = false;
      clearTimeout(timer);
      clearTimeout(again);
    };
    // `asked` is named by its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askedKey, attempt, locale, publicSlug]);

  // Another thing booked or another window: the days listed are not its own.
  function restart(next: { chosen?: string; from?: string }) {
    if (next.chosen !== undefined) setChosen(next.chosen);
    if (next.from !== undefined) setFrom(next.from);
    setStarts(undefined);
    pickStart("");
    setProblem(undefined);
  }
  function pickStart(day: string) {
    setStart(day);
    setEnds(undefined);
    setEnd("");
  }
  const lengthOf = (day: string) =>
    Math.round(
      (Date.parse(`${day}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
        86400000,
    ) + (unit === "day" ? 1 : 0);

  const book = form.handleSubmit(async ({ notes, ...customer }) => {
    if (!asked || !plan) return;
    if (documents.some((document) => !accepted[document.text_id])) return;
    try {
      const created = await createPublicStay(
        publicSlug,
        {
          ...asked,
          ...(notes.trim() ? { customer_notes: notes.trim() } : {}),
          // The price shown: another one by now is asked about, not charged.
          ...(plan.quote ? { quote_digest: plan.quote.digest } : {}),
          ...ticked(documents, marketing),
          // The page's language: the documents above are in it.
          customer: { ...customer, phone: customer.phone.trim(), locale },
        },
        crypto.randomUUID(),
      );
      setBooked(created);
      setProblem(undefined);
    } catch (error) {
      const code = error instanceof ApiProblemError ? error.problem.code : "";
      if (error instanceof ApiProblemError && code === "quote_changed") {
        const detail = error.problem.detail as {
          quote?: BookingPublicQuote | null;
        };
        setPlanned({
          key: askedKey,
          plan: { ...plan, quote: detail.quote ?? null },
        });
        setProblem(t("priceChanged"));
        return;
      }
      if (error instanceof ApiProblemError && code === "documents_changed") {
        const detail = error.problem.detail as Partial<BookingPublicConsents>;
        onDocuments(detail.documents ?? []);
        setAccepted({});
        setTried(false);
        setProblem(t("documentsChanged"));
        return;
      }
      const languages = otherLanguages(error);
      if (languages) {
        onElsewhere(languages);
        return;
      }
      if (code === "slot_unavailable") {
        // Somebody took it a moment earlier: the days are asked for again.
        restart({});
        setProblem(t("stayTaken"));
        return;
      }
      setProblem(t("stayCreateError"));
    }
  });
  // What is left unchosen is said together with the fields left empty.
  const submit = (event: FormEvent<HTMLFormElement>) => {
    setTried(true);
    return book(event);
  };

  if (booked)
    return (
      <BookedCard
        booked={booked}
        email={form.getValues("email")}
        name={form.getValues("display_name").trim()}
      />
    );
  const months = Array.from(
    new Set((starts ?? []).map((day) => day.slice(0, 7))),
  );
  const onRequest = offer?.confirmation === "on_request";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("stayTitle")}</CardTitle>
        <CardDescription>{t("stayDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" noValidate onSubmit={submit}>
          {stays.length + catalog.services.length > 1 ? (
            <Field>
              <FieldLabel htmlFor="booking-service">{t("service")}</FieldLabel>
              <NativeSelect
                id="booking-service"
                onChange={(event) => onOffer(event.target.value)}
                value={offerId}
              >
                {catalog.services.map((item) => (
                  <option key={String(item.id)} value={String(item.id)}>
                    {item.name}
                  </option>
                ))}
                {stays.map((item) => (
                  <option key={String(item.id)} value={String(item.id)}>
                    {item.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          ) : null}
          {offer?.range_start_local && offer.range_end_local ? (
            <p className="text-sm text-muted-foreground">
              {t("stayHours", {
                unit,
                start: offer.range_start_local.slice(0, 5),
                end: offer.range_end_local.slice(0, 5),
              })}
            </p>
          ) : null}
          {choices.length > 1 ? (
            <FieldSet data-invalid={tried && !choice}>
              <FieldLegend variant="label">{t("stayChoice")}</FieldLegend>
              <div className="grid gap-2">
                {choices.map((item) => (
                  <label
                    className="flex min-h-11 items-start gap-3 rounded-lg border p-3 text-sm has-checked:border-primary"
                    key={item.key}
                  >
                    <input
                      checked={chosen === item.key}
                      className="mt-0.5 size-4 shrink-0"
                      name="booking-stay-choice"
                      onChange={() => restart({ chosen: item.key })}
                      type="radio"
                    />
                    <UnitCover name={item.name} photos={item.photos} />
                    <span className="min-w-0">
                      <span className="font-medium">{item.name}</span>
                      {item.capacity ? (
                        <span className="text-muted-foreground">
                          {" · "}
                          {t("stayCapacity", { count: item.capacity })}
                        </span>
                      ) : null}
                      {item.description ? (
                        <span className="block wrap-anywhere text-muted-foreground">
                          {item.description}
                        </span>
                      ) : null}
                      <UnitFacts unit={item} />
                    </span>
                  </label>
                ))}
              </div>
              {tried && !choice ? (
                <FieldError errors={[{ message: t("stayChoiceRequired") }]} />
              ) : null}
            </FieldSet>
          ) : choice ? (
            <p className="text-sm">
              <span className="font-medium">{choice.name}</span>
              {choice.capacity ? (
                <span className="text-muted-foreground">
                  {" · "}
                  {t("stayCapacity", { count: choice.capacity })}
                </span>
              ) : null}
              {choice.description ? (
                <span className="block wrap-anywhere text-muted-foreground">
                  {choice.description}
                </span>
              ) : null}
              <UnitFacts unit={choice} />
            </p>
          ) : null}
          {/* What is chosen, in pictures: each opens large in a new tab. */}
          {choice ? (
            <UnitGallery name={choice.name} photos={choice.photos} />
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="booking-people">
                {t("stayPeople")}
              </FieldLabel>
              <Input
                id="booking-people"
                inputMode="numeric"
                max={choice?.capacity ?? 99}
                min={0}
                onChange={(event) => setPeople(event.target.value)}
                type="number"
                value={people}
              />
            </Field>
            {categories.map((category) => {
              const id = `booking-category-${category.id}`;
              return (
                <Field key={String(category.id)}>
                  <FieldLabel htmlFor={id}>{category.name}</FieldLabel>
                  <Input
                    id={id}
                    inputMode="numeric"
                    max={99}
                    min={0}
                    onChange={(event) =>
                      setOthers({
                        ...others,
                        [String(category.id)]: event.target.value,
                      })
                    }
                    type="number"
                    value={others[String(category.id)] ?? "0"}
                  />
                </Field>
              );
            })}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field data-invalid={tried && !start}>
              <FieldLabel htmlFor="booking-arrival">
                {t(unit === "day" ? "stayFirstDay" : "stayArrival")}
              </FieldLabel>
              <NativeSelect
                aria-invalid={tried && !start}
                disabled={!starts?.length}
                id="booking-arrival"
                onChange={(event) => pickStart(event.target.value)}
                value={start}
              >
                <option value="">{t("choose")}</option>
                {months.map((month) => (
                  <optgroup
                    key={month}
                    label={formatDay(`${month}-01`, locale, {
                      month: "long",
                      year: "numeric",
                    })}
                  >
                    {(starts ?? [])
                      .filter((day) => day.startsWith(month))
                      .map((day) => (
                        <option key={day} value={day}>
                          {formatDay(day, locale, {
                            weekday: "short",
                            day: "numeric",
                            month: "long",
                          })}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </NativeSelect>
              {tried && !start ? (
                <FieldError errors={[{ message: t("stayDatesRequired") }]} />
              ) : null}
            </Field>
            <Field data-invalid={tried && Boolean(start) && !end}>
              <FieldLabel htmlFor="booking-departure">
                {t(unit === "day" ? "stayLastDay" : "stayDeparture")}
              </FieldLabel>
              <NativeSelect
                aria-invalid={tried && Boolean(start) && !end}
                disabled={!ends?.length}
                id="booking-departure"
                onChange={(event) => setEnd(event.target.value)}
                value={end}
              >
                <option value="">{t("choose")}</option>
                {(ends ?? []).map((day) => (
                  <option key={day} value={day}>
                    {t("stayEndOption", {
                      day: formatDay(day, locale, {
                        weekday: "short",
                        day: "numeric",
                        month: "long",
                      }),
                      count: lengthOf(day),
                      unit,
                    })}
                  </option>
                ))}
              </NativeSelect>
              {tried && start && !end ? (
                <FieldError errors={[{ message: t("stayDatesRequired") }]} />
              ) : null}
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {from > today ? (
              <Button
                onClick={() =>
                  restart({
                    from: [addDays(from, -WINDOW_DAYS - 1), today].sort()[1],
                  })
                }
                type="button"
                variant="outline"
              >
                {t("stayEarlier")}
              </Button>
            ) : null}
            {until < lastDay ? (
              <Button
                disabled={Boolean(choice) && !starts}
                onClick={() => restart({ from: addDays(until, 1) })}
                type="button"
                variant="outline"
              >
                {t("stayLater")}
              </Button>
            ) : null}
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {!choice
                ? null
                : !starts || (start && !ends)
                  ? t("loadingTimes")
                  : starts.length === 0
                    ? t("stayNoDays", {
                        from: formatDay(from, locale, { dateStyle: "long" }),
                        to: formatDay(until, locale, { dateStyle: "long" }),
                      })
                    : null}
            </p>
          </div>
          <ExtrasPicker
            currency={catalog.currency ?? "PLN"}
            onPick={setPicked}
            options={options}
            picked={picked}
          />
          {asked && !plan && !refusal ? (
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {t("stayChecking")}
            </p>
          ) : null}
          {refusal ? (
            <p className="text-sm text-destructive" role="alert">
              {t("stayRefused", {
                reason: refusal,
                count: choice?.capacity ?? 0,
              })}
            </p>
          ) : null}
          {plan?.quote ? <QuoteSummary quote={plan.quote} /> : null}
          <ContactFields
            contact={contact}
            errors={form.formState.errors}
            notesHint={t("stayNotesHint")}
            register={(name) => form.register(name)}
          />
          <DocumentBoxes
            accepted={accepted}
            documents={documents}
            marketing={marketing}
            onAccept={(textId, checked) =>
              setAccepted({ ...accepted, [textId]: checked })
            }
            unaccepted={tried}
          />
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {/* The company answers each booking of this offer itself. */}
          {onRequest ? (
            <FieldDescription role="note">
              {t("onRequestHint", { hours: offer?.response_hours ?? 24 })}
            </FieldDescription>
          ) : null}
          <Button
            disabled={form.formState.isSubmitting || Boolean(asked && !plan)}
            type="submit"
          >
            {t(onRequest ? "request" : "book")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
