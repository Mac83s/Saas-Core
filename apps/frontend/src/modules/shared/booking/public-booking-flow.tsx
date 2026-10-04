"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  createPublicBookingAppointment,
  getPublicBookingCatalog,
  getPublicBookingConsents,
  getPublicBookingDays,
  getPublicBookingQuote,
  getPublicBookingTimes,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicChoice,
  type BookingPublicConsents,
  type BookingPublicQuote,
  type BookingSlotTimeList,
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
import { Textarea } from "@saas-core/ui/components/textarea";

import {
  addDays,
  dateFormat,
  formatDay,
  formatWhen,
  wallClock,
} from "./calendar-time";
import { QuoteSummary } from "./quote-summary";
import { TransferDetails } from "./transfer-details";

type Values = {
  service_id: string;
  location_id: string;
  starts_at: string;
  display_name: string;
  email: string;
  phone: string;
  notes: string;
};

/** An .ics file for the customer's own calendar: when, what and where. */
function calendarFile(visit: BookingPublicAppointment): string {
  const stamp = (value: string | Date) =>
    new Date(value)
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(/\.\d{3}/, "");
  const text = (value: string) => value.replace(/[\\,;]/g, "\\$&");
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SaaS Core//Booking//PL",
    "BEGIN:VEVENT",
    `UID:${visit.id}@booking`,
    `DTSTAMP:${stamp(new Date())}`,
    `DTSTART:${stamp(visit.starts_at)}`,
    `DTEND:${stamp(visit.ends_at)}`,
    `SUMMARY:${text(visit.service_name)}`,
    `LOCATION:${text(visit.location_name)}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
}

export function PublicBookingFlow({ publicSlug }: { publicSlug: string }) {
  const t = useTranslations("PublicBooking");
  const documentNames = useTranslations("CustomerDocument");
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingPublicCatalog>();
  // The company's documents in force in the page's language (ADR-073 §9),
  // the ones ticked, and whether a booking was tried without them. A list
  // that did not load is not a way round them: the server answers a booking
  // without them with the list.
  const [documents, setDocuments] = useState<
    BookingPublicConsents["documents"]
  >([]);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [unaccepted, setUnaccepted] = useState(false);
  // The search the days belong to, the days it found, the day chosen and its
  // times; an unset list is one still being asked for.
  const [query, setQuery] = useState<
    {
      service_id: string;
      location_id: string;
    } & BookingPublicChoice
  >();
  const [days, setDays] = useState<string[]>();
  const [day, setDay] = useState("");
  const [times, setTimes] = useState<BookingSlotTimeList["items"]>();
  const [booked, setBooked] = useState<BookingPublicAppointment>();
  const [problem, setProblem] = useState<string>();
  // „Do kogo?”: nobody in particular, or the team / person the service offers.
  const [choice, setChoice] = useState<BookingPublicChoice>({});
  // Which contact the company requires online (booking.online.contact, B9).
  const contact = catalog?.online.contact ?? "email";
  const schema = useMemo(
    () =>
      z
        .object({
          service_id: z.string().uuid(t("required")),
          location_id: z.string().uuid(t("required")),
          starts_at: z.string().min(1, t("pickTime")),
          display_name: z.string().trim().min(1, t("required")).max(160),
          email: z.union([z.literal(""), z.email(t("invalidEmail"))]),
          phone: z.string().trim().max(40),
          notes: z.string().trim().max(500, t("notesTooLong")),
        })
        .superRefine((values, issues) => {
          const email = Boolean(values.email);
          const phone = Boolean(values.phone);
          if (["email", "email_and_phone"].includes(contact) && !email)
            issues.addIssue({
              code: "custom",
              path: ["email"],
              message: t("invalidEmail"),
            });
          if (["phone", "email_and_phone"].includes(contact) && !phone)
            issues.addIssue({
              code: "custom",
              path: ["phone"],
              message: t("phoneRequired"),
            });
          if (contact === "email_or_phone" && !email && !phone)
            issues.addIssue({
              code: "custom",
              path: ["email"],
              message: t("contactRequired"),
            });
        }),
    [contact, t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      location_id: "",
      starts_at: "",
      display_name: "",
      email: "",
      phone: "",
      notes: "",
    },
  });
  const errors = form.formState.errors;
  const zone = catalog?.timezone;
  const serviceId = useWatch({ control: form.control, name: "service_id" });
  const service = catalog?.services.find((x) => String(x.id) === serviceId);
  const offered =
    service?.staff_choice === "team"
      ? (catalog?.teams ?? []).filter((x) => service.team_ids.includes(x.id))
      : service?.staff_choice === "person"
        ? (catalog?.people ?? []).filter((x) =>
            service.person_ids.includes(x.id),
          )
        : [];
  const choiceKey =
    service?.staff_choice === "person" ? "person_id" : "team_id";
  const loading = (!!query && !days) || (!!day && !times);
  // The extras the customer may add to this service, and how many of each.
  const options = (catalog?.extras ?? []).filter(
    (x) => String(x.service_id) === serviceId && !x.mandatory,
  );
  const [picked, setPicked] = useState<Record<string, number>>({});
  const extras = useMemo(
    () =>
      Object.entries(picked)
        .filter(([, quantity]) => quantity > 0)
        .map(([extra_id, quantity]) => ({ extra_id, quantity })),
    [picked],
  );
  // The price of what is chosen now; an answer for an earlier choice is not
  // shown. No price shown never stops a booking: the server prices it anyway.
  const startsAt = useWatch({ control: form.control, name: "starts_at" });
  const quoteKey =
    serviceId && startsAt ? JSON.stringify([serviceId, startsAt, extras]) : "";
  const [priced, setPriced] = useState<{
    key: string;
    quote: BookingPublicQuote | null;
  }>();
  const quote = priced?.key === quoteKey ? priced.quote : undefined;
  const money = (minor: number, currency: string) =>
    new Intl.NumberFormat(locale, { style: "currency", currency }).format(
      minor / 100,
    );

  useEffect(() => {
    void getPublicBookingCatalog(publicSlug)
      .then(setCatalog)
      .catch(() => setProblem(t("loadError")));
  }, [publicSlug, t]);
  useEffect(() => {
    void getPublicBookingConsents(publicSlug, locale)
      .then((value) => setDocuments(value.documents))
      .catch(() => undefined);
  }, [locale, publicSlug]);

  // Each answer is dropped once the customer has moved on to another search
  // or day, as in useFreeSlots: a late reply must not fill in the wrong list.
  useEffect(() => {
    if (!query || !zone) return;
    let current = true;
    // The business's today: the days offered are its calendar, not the browser's.
    const from = wallClock(new Date(), zone).day;
    getPublicBookingDays(publicSlug, {
      ...query,
      from,
      // As far ahead as the company takes bookings online (B3).
      to: catalog?.online.last_day ?? addDays(from, 14),
    })
      .then((value) => {
        if (!current) return;
        setDays(value);
        setProblem(undefined);
      })
      .catch(() => {
        if (!current) return;
        setQuery(undefined);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
  }, [catalog?.online.last_day, publicSlug, query, t, zone]);
  useEffect(() => {
    if (!quoteKey) return;
    let current = true;
    getPublicBookingQuote(publicSlug, {
      service_id: serviceId,
      starts_at: startsAt,
      extras,
      locale,
    })
      .then((value) => {
        if (current) setPriced({ key: quoteKey, quote: value });
      })
      .catch(() => {
        if (current) setPriced({ key: quoteKey, quote: null });
      });
    return () => {
      current = false;
    };
  }, [extras, locale, publicSlug, quoteKey, serviceId, startsAt]);
  useEffect(() => {
    if (!query || !day) return;
    let current = true;
    getPublicBookingTimes(publicSlug, { ...query, date: day })
      .then((value) => {
        if (!current) return;
        setTimes(value);
        setProblem(undefined);
      })
      .catch(() => {
        if (!current) return;
        setTimes([]);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
  }, [day, publicSlug, query, t]);

  // Another service or place: the days and times listed are no longer its own.
  function reset() {
    form.clearErrors(["service_id", "location_id"]);
    setQuery(undefined);
    setDays(undefined);
    pickDay("");
  }
  function choose(next: BookingPublicChoice) {
    setChoice(next);
    reset();
  }
  function pickDay(value: string) {
    setDay(value);
    setTimes(undefined);
    form.setValue("starts_at", "");
  }
  const search = async () => {
    if (!(await form.trigger(["service_id", "location_id"]))) return;
    reset();
    setQuery({
      service_id: form.getValues("service_id"),
      location_id: form.getValues("location_id"),
      ...choice,
    });
  };
  const book = form.handleSubmit(
    async ({ display_name, email, phone, notes, ...booking }) => {
      if (documents.some((document) => !accepted[document.text_id])) return;
      try {
        // Who takes the visit, and the room it needs, is the server's pick
        // (ADR-058 §4) — within the team or the person the customer chose.
        const created = await createPublicBookingAppointment(
          publicSlug,
          {
            ...booking,
            ...(query?.team_id ? { team_id: query.team_id } : {}),
            ...(query?.person_id ? { person_id: query.person_id } : {}),
            ...(notes.trim() ? { customer_notes: notes.trim() } : {}),
            ...(extras.length ? { extras } : {}),
            // The price shown: another one by now is asked about, not charged.
            ...(quote ? { quote_digest: quote.digest } : {}),
            // The texts ticked: another one in force by now is shown and
            // asked about, never accepted for the customer.
            ...(documents.length
              ? {
                  consents: {
                    documents: documents.map((document) => document.text_id),
                  },
                }
              : {}),
            customer: {
              display_name,
              email,
              phone: phone.trim(),
              // The page's language: the documents above are in it.
              locale,
            },
          },
          crypto.randomUUID(),
        );
        setBooked(created);
        setProblem(undefined);
      } catch (error) {
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "quote_changed"
        ) {
          const detail = error.problem.detail as {
            quote?: BookingPublicQuote | null;
          };
          setPriced({ key: quoteKey, quote: detail.quote ?? null });
          setProblem(t("priceChanged"));
          return;
        }
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "documents_changed"
        ) {
          const detail = error.problem.detail as Partial<BookingPublicConsents>;
          setDocuments(detail.documents ?? []);
          setAccepted({});
          setUnaccepted(false);
          setProblem(t("documentsChanged"));
          return;
        }
        setProblem(t("createError"));
      }
    },
  );
  // A box left empty is said together with the fields left empty.
  const submit = (event: FormEvent<HTMLFormElement>) => {
    setUnaccepted(true);
    return book(event);
  };
  // The business's wall clock, zone named: the customer may be elsewhere, and
  // the autumn hour that happens twice reads as two different times.
  const clock = zone
    ? dateFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: zone,
        timeZoneName: "short",
      })
    : undefined;

  if (booked) {
    // The booking holds its time and waits (ADR-072 §9): for the company's
    // answer where the offer is taken on request, or for the transfer where
    // it asks for money first.
    const state =
      booked.status === "pending_request"
        ? "requested"
        : booked.status === "pending_payment"
          ? "pending"
          : "confirmed";
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t(state)}</CardTitle>
          <CardDescription>
            {t(`${state}Description`, {
              name: form.getValues("display_name").trim(),
              email: form.getValues("email"),
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t("when")}</dt>
            <dd className="font-medium">
              {formatWhen(booked, locale, booked.timezone)}
            </dd>
            <dt className="text-muted-foreground">{t("service")}</dt>
            <dd className="font-medium">{booked.service_name}</dd>
            {booked.team_name ? (
              <>
                <dt className="text-muted-foreground">{t("chosenTeam")}</dt>
                <dd className="font-medium">{booked.team_name}</dd>
              </>
            ) : null}
            {booked.person_name ? (
              <>
                <dt className="text-muted-foreground">{t("seenBy")}</dt>
                <dd className="font-medium">{booked.person_name}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">{t("status")}</dt>
            <dd className="font-medium">
              {t(
                state === "requested"
                  ? "statusRequested"
                  : state === "pending"
                    ? "statusPending"
                    : "statusConfirmed",
              )}
            </dd>
            {state === "requested" && booked.hold_expires_at ? (
              <>
                <dt className="text-muted-foreground">{t("answerBy")}</dt>
                <dd className="font-medium">
                  {dateFormat(locale, {
                    dateStyle: "full",
                    timeStyle: "short",
                    timeZone: booked.timezone,
                  }).format(new Date(booked.hold_expires_at))}
                </dd>
              </>
            ) : null}
          </dl>
          {booked.payment ? (
            <TransferDetails payment={booked.payment} zone={booked.timezone} />
          ) : null}
          {booked.quote ? (
            <QuoteSummary
              quote={booked.quote}
              settled={state === "confirmed"}
            />
          ) : null}
          <div className="flex flex-wrap gap-3">
            {booked.self_service_token ? (
              <a
                className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
                href={`/${locale}/booking/${encodeURIComponent(booked.self_service_token)}`}
              >
                {/* A booking that waits can be given up, not moved. */}
                {t(state === "confirmed" ? "manage" : "manageWaiting")}
              </a>
            ) : null}
            {/* Into the calendar once it is certain: a booking that waits
                may still expire or be declined. */}
            {state === "confirmed" ? (
              <a
                className="inline-flex min-h-11 items-center justify-center rounded-lg border px-4 text-sm font-medium"
                download="wizyta.ics"
                href={`data:text/calendar;charset=utf-8,${encodeURIComponent(calendarFile(booked))}`}
              >
                {t("addToCalendar")}
              </a>
            ) : null}
          </div>
          <p className="text-sm text-muted-foreground">{t("manageHint")}</p>
        </CardContent>
      </Card>
    );
  }
  // The company paused online booking (ADR-078, booking.online): say so
  // instead of a form the server would refuse.
  if (catalog?.online.paused)
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription role="status">
            {catalog.online.resume_on
              ? t("pausedUntil", {
                  date: new Intl.DateTimeFormat(locale, {
                    dateStyle: "long",
                  }).format(new Date(`${catalog.online.resume_on}T12:00:00`)),
                })
              : t("paused")}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" noValidate onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field data-invalid={Boolean(errors.service_id)}>
              <FieldLabel htmlFor="booking-service">{t("service")}</FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.service_id)}
                id="booking-service"
                {...form.register("service_id", {
                  onChange: () => {
                    setPicked({});
                    choose({});
                  },
                })}
              >
                <option value="">{t("choose")}</option>
                {catalog?.services.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.service_id]} />
            </Field>
            <Field data-invalid={Boolean(errors.location_id)}>
              <FieldLabel htmlFor="booking-location">
                {t("location")}
              </FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.location_id)}
                id="booking-location"
                {...form.register("location_id", { onChange: reset })}
              >
                <option value="">{t("choose")}</option>
                {catalog?.locations.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.location_id]} />
            </Field>
          </div>
          {offered.length ? (
            <FieldSet>
              <FieldLegend variant="label">{t("whoLegend")}</FieldLegend>
              <div className="grid gap-1">
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={!choice.team_id && !choice.person_id}
                    className="size-4"
                    name="booking-who"
                    onChange={() => choose({})}
                    type="radio"
                  />
                  {t(choiceKey === "team_id" ? "anyTeam" : "anyPerson")}
                </label>
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={Boolean(choice.team_id || choice.person_id)}
                    className="size-4"
                    name="booking-who"
                    onChange={() =>
                      choose({ [choiceKey]: String(offered[0].id) })
                    }
                    type="radio"
                  />
                  {t(choiceKey === "team_id" ? "pickTeam" : "pickPerson")}
                </label>
              </div>
              {choice.team_id || choice.person_id ? (
                <NativeSelect
                  aria-label={t(choiceKey === "team_id" ? "team" : "person")}
                  onChange={(event) =>
                    choose({ [choiceKey]: event.target.value })
                  }
                  value={choice.team_id ?? choice.person_id}
                >
                  {offered.map((x) => (
                    <option key={String(x.id)} value={String(x.id)}>
                      {x.name}
                    </option>
                  ))}
                </NativeSelect>
              ) : null}
              <FieldDescription>
                {t(choiceKey === "team_id" ? "teamsHint" : "peopleHint")}
              </FieldDescription>
            </FieldSet>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={loading}
              onClick={() => void search()}
              type="button"
              variant="outline"
            >
              {t("search")}
            </Button>
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {loading
                ? t("loadingTimes")
                : days?.length === 0
                  ? t("noDays")
                  : null}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="booking-day">{t("day")}</FieldLabel>
              <NativeSelect
                disabled={!days?.length}
                id="booking-day"
                onChange={(event) => pickDay(event.target.value)}
                value={day}
              >
                <option value="">{t("choose")}</option>
                {days?.map((item) => (
                  <option key={item} value={item}>
                    {formatDay(item, locale, { dateStyle: "full" })}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field data-invalid={Boolean(errors.starts_at)}>
              <FieldLabel htmlFor="booking-slot">{t("slot")}</FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.starts_at)}
                id="booking-slot"
                {...form.register("starts_at")}
              >
                <option value="">{t("choose")}</option>
                {times?.map((x) => (
                  <option key={x.starts_at} value={x.starts_at}>
                    {clock?.format(new Date(x.starts_at))}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.starts_at]} />
            </Field>
          </div>
          {options.length ? (
            <FieldSet>
              <FieldLegend variant="label">{t("extrasLegend")}</FieldLegend>
              <div className="grid gap-1">
                {options.map((option) => {
                  const id = String(option.id);
                  const label = t("extraOption", {
                    name: option.name,
                    amount: money(
                      option.unit_gross_minor,
                      catalog?.currency ?? "PLN",
                    ),
                    basis: option.basis,
                  });
                  return option.max_quantity > 1 ? (
                    <label
                      className="flex min-h-11 items-center justify-between gap-3 text-sm"
                      key={id}
                    >
                      <span className="min-w-0 wrap-anywhere">{label}</span>
                      {/* The select's box is this narrow: `NativeSelect`
                          draws its arrow at the right edge of its own box,
                          which otherwise is the whole row. */}
                      <span className="w-20 shrink-0">
                        <NativeSelect
                          aria-label={t("extraQuantity", { name: option.name })}
                          onChange={(event) =>
                            setPicked({
                              ...picked,
                              [id]: Number(event.target.value),
                            })
                          }
                          value={picked[id] ?? 0}
                        >
                          {Array.from(
                            { length: option.max_quantity + 1 },
                            (_, count) => (
                              <option key={count} value={count}>
                                {count}
                              </option>
                            ),
                          )}
                        </NativeSelect>
                      </span>
                    </label>
                  ) : (
                    <label
                      className="flex min-h-11 items-center gap-2 text-sm"
                      key={id}
                    >
                      <input
                        checked={Boolean(picked[id])}
                        className="size-4"
                        onChange={(event) =>
                          setPicked({
                            ...picked,
                            [id]: event.target.checked ? 1 : 0,
                          })
                        }
                        type="checkbox"
                      />
                      {label}
                    </label>
                  );
                })}
              </div>
            </FieldSet>
          ) : null}
          {quote ? <QuoteSummary quote={quote} /> : null}
          <Field data-invalid={Boolean(errors.display_name)}>
            <FieldLabel htmlFor="booking-name">{t("name")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.display_name)}
              id="booking-name"
              {...form.register("display_name")}
            />
            <FieldError errors={[errors.display_name]} />
          </Field>
          <Field data-invalid={Boolean(errors.email)}>
            <FieldLabel htmlFor="booking-email">
              {["email", "email_and_phone"].includes(contact)
                ? t("email")
                : t("emailOptional")}
            </FieldLabel>
            <Input
              aria-invalid={Boolean(errors.email)}
              autoComplete="email"
              id="booking-email"
              type="email"
              {...form.register("email")}
            />
            <FieldError errors={[errors.email]} />
          </Field>
          {contact === "email" ? null : (
            <Field data-invalid={Boolean(errors.phone)}>
              <FieldLabel htmlFor="booking-phone">
                {contact === "email_or_phone" ? t("phoneOptional") : t("phone")}
              </FieldLabel>
              <Input
                aria-invalid={Boolean(errors.phone)}
                autoComplete="tel"
                id="booking-phone"
                type="tel"
                {...form.register("phone")}
              />
              <FieldError errors={[errors.phone]} />
            </Field>
          )}
          <Field data-invalid={Boolean(errors.notes)}>
            <FieldLabel htmlFor="booking-notes">{t("notes")}</FieldLabel>
            <Textarea
              aria-invalid={Boolean(errors.notes)}
              id="booking-notes"
              maxLength={500}
              rows={3}
              {...form.register("notes")}
            />
            <FieldDescription>{t("notesHint")}</FieldDescription>
            <FieldError errors={[errors.notes]} />
          </Field>
          {documents.map((document) => {
            const missing = unaccepted && !accepted[document.text_id];
            const id = `booking-document-${document.kind}`;
            return (
              <Field data-invalid={missing} key={document.text_id}>
                <label
                  className="flex min-h-11 items-center gap-2 text-sm"
                  htmlFor={id}
                >
                  <input
                    aria-describedby={`${id}-read`}
                    aria-invalid={missing}
                    checked={Boolean(accepted[document.text_id])}
                    className="size-4 shrink-0"
                    id={id}
                    onChange={(event) =>
                      setAccepted({
                        ...accepted,
                        [document.text_id]: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />
                  {document.statement}
                </label>
                <FieldDescription id={`${id}-read`}>
                  <a
                    className="underline underline-offset-4"
                    href={document.url}
                    rel="noopener"
                    target="_blank"
                  >
                    {documentNames(`kinds.${document.kind}`)}
                  </a>
                </FieldDescription>
                {missing ? (
                  <FieldError errors={[{ message: t("documentRequired") }]} />
                ) : null}
              </Field>
            );
          })}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {/* The company answers each booking of this service itself. */}
          {service?.confirmation === "on_request" ? (
            <p className="text-sm text-muted-foreground" role="note">
              {t("onRequestHint", { hours: service.response_hours ?? 24 })}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {t(service?.confirmation === "on_request" ? "request" : "book")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
