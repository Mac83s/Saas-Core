"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  createPublicBookingAppointment,
  getPublicBookingCatalog,
  getPublicBookingDays,
  getPublicBookingTimes,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicChoice,
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
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingPublicCatalog>();
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

  useEffect(() => {
    void getPublicBookingCatalog(publicSlug)
      .then(setCatalog)
      .catch(() => setProblem(t("loadError")));
  }, [publicSlug, t]);

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
  const submit = form.handleSubmit(
    async ({ display_name, email, phone, notes, ...booking }) => {
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
            customer: {
              display_name,
              email,
              phone: phone.trim(),
              locale: locale === "en" ? "en" : "pl",
            },
          },
          crypto.randomUUID(),
        );
        setBooked(created);
        setProblem(undefined);
      } catch {
        setProblem(t("createError"));
      }
    },
  );
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

  if (booked)
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("confirmed")}</CardTitle>
          <CardDescription>
            {t("confirmedDescription", {
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
            <dd className="font-medium">{t("statusConfirmed")}</dd>
          </dl>
          <div className="flex flex-wrap gap-3">
            {booked.self_service_token ? (
              <a
                className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
                href={`/${locale}/booking/${encodeURIComponent(booked.self_service_token)}`}
              >
                {t("manage")}
              </a>
            ) : null}
            <a
              className="inline-flex min-h-11 items-center justify-center rounded-lg border px-4 text-sm font-medium"
              download="wizyta.ics"
              href={`data:text/calendar;charset=utf-8,${encodeURIComponent(calendarFile(booked))}`}
            >
              {t("addToCalendar")}
            </a>
          </div>
          <p className="text-sm text-muted-foreground">{t("manageHint")}</p>
        </CardContent>
      </Card>
    );
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
                  onChange: () => choose({}),
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
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {t("book")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
