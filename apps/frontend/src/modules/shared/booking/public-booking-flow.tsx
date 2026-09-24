"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  createPublicBookingAppointment,
  getPublicBookingCatalog,
  getPublicBookingDays,
  getPublicBookingTimes,
  type BookingPublicCatalog,
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
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { addDays, dateFormat, formatDay, wallClock } from "./calendar-time";

type Values = {
  service_id: string;
  location_id: string;
  starts_at: string;
  display_name: string;
  email: string;
};

export function PublicBookingFlow({ publicSlug }: { publicSlug: string }) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingPublicCatalog>();
  // The search the days belong to, the days it found, the day chosen and its
  // times; an unset list is one still being asked for.
  const [query, setQuery] = useState<{
    service_id: string;
    location_id: string;
  }>();
  const [days, setDays] = useState<string[]>();
  const [day, setDay] = useState("");
  const [times, setTimes] = useState<BookingSlotTimeList["items"]>();
  const [token, setToken] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        service_id: z.string().uuid(t("required")),
        location_id: z.string().uuid(t("required")),
        starts_at: z.string().min(1, t("pickTime")),
        display_name: z.string().trim().min(1, t("required")).max(160),
        email: z.email(t("invalidEmail")),
      }),
    [t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      location_id: "",
      starts_at: "",
      display_name: "",
      email: "",
    },
  });
  const errors = form.formState.errors;
  const zone = catalog?.timezone;
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
    getPublicBookingDays(publicSlug, { ...query, from, to: addDays(from, 14) })
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
  }, [publicSlug, query, t, zone]);
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
    });
  };
  const submit = form.handleSubmit(
    async ({ display_name, email, ...booking }) => {
      try {
        // Who takes the visit, and the room it needs, is the server's pick
        // (ADR-058 §4): the form names only the service, place and time.
        const created = await createPublicBookingAppointment(
          publicSlug,
          {
            ...booking,
            customer: {
              display_name,
              email,
              phone: "",
              locale: locale === "en" ? "en" : "pl",
            },
          },
          crypto.randomUUID(),
        );
        setToken(created.self_service_token ?? undefined);
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

  if (token)
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("confirmed")}</CardTitle>
          <CardDescription>{t("confirmedDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <a
            className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
            href={`/${locale}/booking/${encodeURIComponent(token)}`}
          >
            {t("manage")}
          </a>
        </CardContent>
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
                {...form.register("service_id", { onChange: reset })}
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
            <FieldLabel htmlFor="booking-email">E-mail</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.email)}
              id="booking-email"
              type="email"
              {...form.register("email")}
            />
            <FieldError errors={[errors.email]} />
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
