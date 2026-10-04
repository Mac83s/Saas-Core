"use client";

import { useLocale, useTranslations } from "next-intl";
import type { FieldError, UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicConsents,
} from "@saas-core/api-client";
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
  FieldError as FieldProblem,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { nativeName } from "#lib/company-locales";
import { dateFormat, formatWhen, wallClock } from "./calendar-time";
import { QuoteSummary } from "./quote-summary";
import { TransferDetails } from "./transfer-details";

/**
 * What the public form asks of every customer, whatever they book — a visit
 * at a time or a stay from–to: who they are, the company's documents, the
 * extras, and what they are told once it is booked.
 */

export type ContactValues = {
  display_name: string;
  email: string;
  phone: string;
  notes: string;
};

type Translate = (key: string) => string;

/** Which contact the company requires online (booking.online.contact, B9). */
export type ContactRule = BookingPublicCatalog["online"]["contact"];

export function contactShape(t: Translate) {
  return {
    display_name: z.string().trim().min(1, t("required")).max(160),
    email: z.union([z.literal(""), z.email(t("invalidEmail"))]),
    phone: z.string().trim().max(40),
    notes: z.string().trim().max(500, t("notesTooLong")),
  };
}

/** The contact the company requires, said at the field that lacks it. */
export function contactIssues(contact: ContactRule, t: Translate) {
  return (
    values: Pick<ContactValues, "email" | "phone">,
    issues: z.RefinementCtx,
  ) => {
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
  };
}

export function ContactFields({
  contact,
  errors,
  notesHint,
  register,
}: {
  contact: ContactRule;
  errors: Partial<Record<keyof ContactValues, FieldError>>;
  /** What „Uwagi” are for, where it is not a visit that is booked. */
  notesHint?: string;
  register: (name: keyof ContactValues) => UseFormRegisterReturn;
}) {
  const t = useTranslations("PublicBooking");
  return (
    <>
      <Field data-invalid={Boolean(errors.display_name)}>
        <FieldLabel htmlFor="booking-name">{t("name")}</FieldLabel>
        <Input
          aria-invalid={Boolean(errors.display_name)}
          autoComplete="name"
          id="booking-name"
          {...register("display_name")}
        />
        <FieldProblem errors={[errors.display_name]} />
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
          {...register("email")}
        />
        <FieldProblem errors={[errors.email]} />
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
            {...register("phone")}
          />
          <FieldProblem errors={[errors.phone]} />
        </Field>
      )}
      <Field data-invalid={Boolean(errors.notes)}>
        <FieldLabel htmlFor="booking-notes">{t("notes")}</FieldLabel>
        <Textarea
          aria-invalid={Boolean(errors.notes)}
          id="booking-notes"
          maxLength={500}
          rows={3}
          {...register("notes")}
        />
        <FieldDescription>{notesHint ?? t("notesHint")}</FieldDescription>
        <FieldProblem errors={[errors.notes]} />
      </Field>
    </>
  );
}

type PublicDocument = BookingPublicConsents["documents"][number];

/** The marketing consent the company asks for: its sentence, and whether the
 *  customer ticked it. */
export type MarketingBox = {
  statement: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

/** What the customer ticked, as a booking takes it: the texts shown — another
 *  one in force by now is shown and asked about, never accepted for the
 *  customer — and the marketing consent, when they gave it. */
export function ticked(documents: PublicDocument[], marketing?: MarketingBox) {
  const consents: { documents?: string[]; marketing?: boolean } = {};
  if (documents.length)
    consents.documents = documents.map((document) => document.text_id);
  if (marketing?.checked) consents.marketing = true;
  return consents.documents || consents.marketing ? { consents } : {};
}

/** The languages to offer instead, when the server refused a booking because
 *  the booking terms have no text in this one (`booking_language_unavailable`). */
export function otherLanguages(error: unknown): string[] | undefined {
  if (
    !(error instanceof ApiProblemError) ||
    error.problem.code !== "booking_language_unavailable"
  )
    return undefined;
  return (error.problem.detail as { locales?: string[] }).locales ?? [];
}

/** The company's booking terms have no text in the page's language, so
 *  nobody books online in it (ADR-073 §9): said plainly, with the languages
 *  that have them — like the card of a paused form. */
export function LanguageUnavailable({
  locales,
  publicSlug,
}: {
  locales: string[];
  publicSlug: string;
}) {
  const t = useTranslations("PublicBooking");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription role="status">
          {t("languageUnavailable")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">
          {t(locales.length ? "languageOffer" : "languageNone")}
        </p>
        {locales.length ? (
          <ul className="flex flex-wrap gap-3">
            {locales.map((code) => (
              <li key={code}>
                <a
                  className="inline-flex min-h-11 items-center justify-center rounded-lg border px-4 text-sm font-medium"
                  href={`/${code}/book/${encodeURIComponent(publicSlug)}`}
                  hrefLang={code}
                  lang={code}
                >
                  {nativeName(code)}
                </a>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** The company's documents in force (ADR-073 §9): each a box to tick, with
 *  where the text is read. `unaccepted` — a booking was tried: an empty box
 *  is said together with the fields left empty. Below them the marketing
 *  consent, where the company asks for it: optional, never ticked for the
 *  customer. */
export function DocumentBoxes({
  accepted,
  documents,
  marketing,
  onAccept,
  unaccepted,
}: {
  accepted: Record<string, boolean>;
  documents: PublicDocument[];
  marketing?: MarketingBox;
  onAccept: (textId: string, checked: boolean) => void;
  unaccepted: boolean;
}) {
  const t = useTranslations("PublicBooking");
  const names = useTranslations("CustomerDocument");
  return (
    <>
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
                  onAccept(document.text_id, event.target.checked)
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
                {names(`kinds.${document.kind}`)}
              </a>
            </FieldDescription>
            {missing ? (
              <FieldProblem errors={[{ message: t("documentRequired") }]} />
            ) : null}
          </Field>
        );
      })}
      {marketing ? (
        <Field>
          <label
            className="flex min-h-11 items-center gap-2 text-sm"
            htmlFor="booking-marketing"
          >
            <input
              aria-describedby="booking-marketing-hint"
              checked={marketing.checked}
              className="size-4 shrink-0"
              id="booking-marketing"
              onChange={(event) => marketing.onChange(event.target.checked)}
              type="checkbox"
            />
            {marketing.statement}
          </label>
          <FieldDescription id="booking-marketing-hint">
            {t("marketingHint")}
          </FieldDescription>
        </Field>
      ) : null}
    </>
  );
}

type PublicExtra = NonNullable<BookingPublicCatalog["extras"]>[number];

/** The extras a customer may add, and how many of each. The amounts are
 *  what one comes to; the quote is what counts. */
export function ExtrasPicker({
  currency,
  onPick,
  options,
  picked,
}: {
  currency: string;
  onPick: (next: Record<string, number>) => void;
  options: PublicExtra[];
  picked: Record<string, number>;
}) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const money = (minor: number) =>
    new Intl.NumberFormat(locale, { style: "currency", currency }).format(
      minor / 100,
    );
  if (!options.length) return null;
  return (
    <FieldSet>
      <FieldLegend variant="label">{t("extrasLegend")}</FieldLegend>
      <div className="grid gap-1">
        {options.map((option) => {
          const id = String(option.id);
          const label = t("extraOption", {
            name: option.name,
            amount: money(option.unit_gross_minor),
            basis: option.basis,
          });
          return option.max_quantity > 1 ? (
            <label
              className="flex min-h-11 items-center justify-between gap-3 text-sm"
              key={id}
            >
              <span className="min-w-0 wrap-anywhere">{label}</span>
              {/* The select's box is this narrow: `NativeSelect` draws its
                  arrow at the right edge of its own box, which otherwise is
                  the whole row. */}
              <span className="w-20 shrink-0">
                <NativeSelect
                  aria-label={t("extraQuantity", { name: option.name })}
                  onChange={(event) =>
                    onPick({ ...picked, [id]: Number(event.target.value) })
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
                  onPick({ ...picked, [id]: event.target.checked ? 1 : 0 })
                }
                type="checkbox"
              />
              {label}
            </label>
          );
        })}
      </div>
    </FieldSet>
  );
}

/** The extras picked, as a booking and a quote take them. */
export function pickedExtras(picked: Record<string, number>) {
  return Object.entries(picked)
    .filter(([, quantity]) => quantity > 0)
    .map(([extra_id, quantity]) => ({ extra_id, quantity }));
}

/** The refusals of a stay the pages have their own words for
 *  (`PublicBooking.stayRefused`); anything else is said as „nie można
 *  zarezerwować”. */
const REFUSALS = [
  // Too many questions at once: nothing is wrong with the dates.
  "throttled",
  "unit_capacity_exceeded",
  "slot_unavailable",
  "price_missing",
  "rule_min_length",
  "rule_max_length",
  "rule_notice",
  "beyond_booking_horizon",
];

/** Why the server refused a stay, as a key of `stayRefused`: the first
 *  field problem's code, or the problem's own. */
export function refusalOf(error: unknown): string {
  if (!(error instanceof ApiProblemError)) return "other";
  const code = error.problem.errors?.[0]?.code ?? error.problem.code;
  return REFUSALS.includes(code) ? code : "other";
}

/** A stay's instants on the company's clock, and what it is counted in. */
type StayTime = {
  starts_at: string;
  ends_at: string;
  timezone: string;
  range_unit?: string;
};

/** How many nights or days a stay takes, from its instants on the company's
 *  wall clock: a night's departure day is not one of them. */
export function stayLength(stay: StayTime): number {
  const day = (instant: string) =>
    Date.parse(`${wallClock(instant, stay.timezone).day}T00:00:00Z`);
  const days = Math.round((day(stay.ends_at) - day(stay.starts_at)) / 86400000);
  return stay.range_unit === "day" ? days + 1 : days;
}

/** „7–10 października 2026 · 3 noce”: a stay is told by its days. */
export function useStayWhen() {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  return (stay: StayTime) =>
    t("stayWhen", {
      range: dateFormat(locale, {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: stay.timezone,
      }).formatRange(new Date(stay.starts_at), new Date(stay.ends_at)),
      count: stayLength(stay),
      unit: stay.range_unit === "day" ? "day" : "night",
    });
}

/** „Zameldowanie od 15:00, wymeldowanie do 11:00” on the company's clock. */
export function useStayHours() {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  return (stay: StayTime) => {
    const clock = dateFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: stay.timezone,
    });
    return t("stayHours", {
      unit: stay.range_unit === "day" ? "day" : "night",
      start: clock.format(new Date(stay.starts_at)),
      end: clock.format(new Date(stay.ends_at)),
    });
  };
}

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

/** What the customer is told once it is booked — a visit or a stay. The
 *  booking may hold its time and wait (ADR-072 §9): for the company's answer
 *  where the offer is taken on request, or for the transfer where it asks
 *  for money first. */
export function BookedCard({
  booked,
  email,
  name,
}: {
  booked: BookingPublicAppointment;
  email: string;
  name: string;
}) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const stayWhen = useStayWhen();
  const stayHours = useStayHours();
  const stay = booked.time_model === "range";
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
          {t(`${state}Description`, { name, email })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("when")}</dt>
          <dd className="font-medium">
            {stay ? (
              <>
                {stayWhen(booked)}
                <span className="block font-normal text-muted-foreground">
                  {stayHours(booked)}
                </span>
              </>
            ) : (
              formatWhen(booked, locale, booked.timezone)
            )}
          </dd>
          <dt className="text-muted-foreground">{t("service")}</dt>
          <dd className="font-medium">{booked.service_name}</dd>
          {booked.unit_name ? (
            <>
              <dt className="text-muted-foreground">{t("unit")}</dt>
              <dd className="font-medium">{booked.unit_name}</dd>
            </>
          ) : null}
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
          <QuoteSummary quote={booked.quote} settled={state === "confirmed"} />
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
              download={stay ? "pobyt.ics" : "wizyta.ics"}
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
