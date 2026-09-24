"use client";

import { useEffect, useState } from "react";
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
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const schema = z.object({
  service_id: z.string().uuid(),
  location_id: z.string().uuid(),
  starts_at: z.string().min(1),
  display_name: z.string().trim().min(1).max(160),
  email: z.string().email(),
});

export function PublicBookingFlow({ publicSlug }: { publicSlug: string }) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingPublicCatalog>();
  const [days, setDays] = useState<string[]>([]);
  const [day, setDay] = useState("");
  const [times, setTimes] = useState<BookingSlotTimeList["items"]>([]);
  const [token, setToken] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      location_id: "",
      starts_at: "",
      display_name: "",
      email: "",
    },
  });

  useEffect(() => {
    void getPublicBookingCatalog(publicSlug)
      .then(setCatalog)
      .catch(() => setProblem(t("loadError")));
  }, [publicSlug, t]);

  const search = async () => {
    const service = form.getValues("service_id");
    const location = form.getValues("location_id");
    if (!service || !location) return;
    const from = new Date();
    const to = new Date(from);
    to.setDate(to.getDate() + 14);
    try {
      setDays(
        await getPublicBookingDays(publicSlug, {
          service_id: service,
          location_id: location,
          from: from.toISOString().slice(0, 10),
          to: to.toISOString().slice(0, 10),
        }),
      );
      setDay("");
      setTimes([]);
      form.setValue("starts_at", "");
      setProblem(undefined);
    } catch {
      setProblem(t("loadError"));
    }
  };
  const pickDay = async (value: string) => {
    setDay(value);
    setTimes([]);
    form.setValue("starts_at", "");
    if (!value) return;
    try {
      setTimes(
        await getPublicBookingTimes(publicSlug, {
          service_id: form.getValues("service_id"),
          location_id: form.getValues("location_id"),
          date: value,
        }),
      );
      setProblem(undefined);
    } catch {
      setProblem(t("loadError"));
    }
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
            customer: { display_name, email, phone: "", locale: "pl" },
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
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="booking-service">{t("service")}</Label>
              <NativeSelect
                id="booking-service"
                {...form.register("service_id")}
              >
                <option value="">{t("choose")}</option>
                {catalog?.services.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="booking-location">{t("location")}</Label>
              <NativeSelect
                id="booking-location"
                {...form.register("location_id")}
              >
                <option value="">{t("choose")}</option>
                {catalog?.locations.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <Button onClick={() => void search()} type="button" variant="outline">
            {t("search")}
          </Button>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="booking-day">{t("day")}</Label>
              <NativeSelect
                id="booking-day"
                onChange={(event) => void pickDay(event.target.value)}
                value={day}
              >
                <option value="">{t("choose")}</option>
                {days.map((item) => (
                  <option key={item} value={item}>
                    {/* A calendar date, not an instant: read it in UTC. */}
                    {new Date(item).toLocaleDateString(locale, {
                      dateStyle: "full",
                      timeZone: "UTC",
                    })}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="booking-slot">{t("slot")}</Label>
              <NativeSelect id="booking-slot" {...form.register("starts_at")}>
                <option value="">{t("choose")}</option>
                {times.map((x) => (
                  <option key={x.starts_at} value={x.starts_at}>
                    {new Date(x.starts_at).toLocaleTimeString(locale, {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <div>
            <Label htmlFor="booking-name">{t("name")}</Label>
            <Input id="booking-name" {...form.register("display_name")} />
          </div>
          <div>
            <Label htmlFor="booking-email">E-mail</Label>
            <Input
              id="booking-email"
              type="email"
              {...form.register("email")}
            />
          </div>
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
