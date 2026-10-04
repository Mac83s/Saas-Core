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

import { addDays, wallClock } from "./calendar-time";
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
import { StayDatePicker } from "./stay-date-picker";

type Documents = BookingPublicConsents["documents"];
type Offer = NonNullable<BookingPublicCatalog["stays"]>[number];

/** How far ahead arrivals are looked for where the catalogue names no last
 *  day (an older answer): a quarter. */
const WINDOW_DAYS = 91;

/** What a link to the form chose ahead of the guest (ADR-072, slice 5d) —
 *  a block of the company's site says the offer, what is booked of it, the
 *  days and how many people come. Everything is asked of the server again:
 *  a day that is not free by now is refused like any other. */
export type StayPreset = {
  offer?: string;
  group?: string;
  unit?: string;
  from?: string;
  to?: string;
  people?: string;
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The days a link named, when they can be a stay at all: an arrival that is
 *  not behind us, and an end after it (the same day ends a stay in days). */
function presetDays(
  preset: StayPreset | undefined,
  today: string,
  unit: "night" | "day",
): { start: string; end: string } {
  const start = preset?.from ?? "";
  if (!DAY.test(start) || start < today) return { start: "", end: "" };
  const end = preset?.to ?? "";
  const closes = DAY.test(end) && (unit === "day" ? end >= start : end > start);
  return { start, end: closes ? end : "" };
}
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
  preset,
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
  /** What the link to the form chose of this offer, if it chose anything. */
  preset?: StayPreset;
  publicSlug: string;
}) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const stays = useMemo(() => catalog.stays ?? [], [catalog.stays]);
  const offer = stays.find((item) => String(item.id) === offerId);
  const choices = useMemo(() => choicesOf(offer), [offer]);
  const unit = offer?.range_unit === "day" ? "day" : "night";
  const contact = catalog.online.contact;
  // What is booked: the only choice by itself, otherwise the guest's pick —
  // or the one the link named, when the offer has it.
  const [chosen, setChosen] = useState(() => {
    const key = preset?.group
      ? `group:${preset.group}`
      : preset?.unit
        ? `unit:${preset.unit}`
        : "";
    return choicesOf(offer).some((item) => item.key === key) ? key : "";
  });
  const choice =
    choices.length === 1
      ? choices[0]
      : choices.find((item) => item.key === chosen);
  // Who comes: standard people, and so many of each of the company's
  // categories („Dziecko”, „Pies”).
  // Counts are kept as typed, so a field can be emptied on the way to another
  // number; what is asked of the server are the whole numbers in them.
  const categories = catalog.participant_categories ?? [];
  const [people, setPeople] = useState(() =>
    /^[1-9]\d?$/.test(preset?.people ?? "") ? String(preset?.people) : "2",
  );
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
  // The days: the arrival and the departure picked in the calendar, which
  // asks the server for the days of each month it shows.
  const [today] = useState(() => wallClock(new Date(), catalog.timezone).day);
  const lastDay = catalog.online.period_last_day ?? addDays(today, WINDOW_DAYS);
  const [start, setStart] = useState(
    () => presetDays(preset, today, unit).start,
  );
  const [end, setEnd] = useState(() => presetDays(preset, today, unit).end);
  // Counts the times the days were asked for again from the start.
  const [search, setSearch] = useState(0);
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

  // Another thing booked, or the days asked for again: the days chosen are
  // not its own.
  function restart(next: { chosen?: string }) {
    if (next.chosen !== undefined) setChosen(next.chosen);
    setSearch((count) => count + 1);
    setStart("");
    setEnd("");
    setProblem(undefined);
  }

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
          <FieldSet data-invalid={tried && !(start && end)}>
            <FieldLegend variant="label">{t("stayDates")}</FieldLegend>
            {choice ? (
              <StayDatePicker
                end={end}
                invalid={tried && !(start && end)}
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
                  length: (count) => t("stayLength", { count, unit }),
                }}
                lastDay={lastDay}
                loadEnds={(day) =>
                  getPublicStayEnds(publicSlug, {
                    service_id: offerId,
                    ...choice.target,
                    start: day,
                  })
                }
                loadStarts={(from, to) =>
                  getPublicStayStarts(publicSlug, {
                    service_id: offerId,
                    ...choice.target,
                    from,
                    to,
                  })
                }
                locale={locale}
                months={2}
                onChange={(first, last) => {
                  setStart(first);
                  setEnd(last);
                  setProblem(undefined);
                }}
                searchKey={`${targetKey}#${search}`}
                start={start}
                today={today}
                unit={unit}
              />
            ) : (
              <FieldDescription>{t("stayChoiceFirst")}</FieldDescription>
            )}
            {tried && choice && !(start && end) ? (
              <FieldError errors={[{ message: t("stayDatesRequired") }]} />
            ) : null}
          </FieldSet>
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
