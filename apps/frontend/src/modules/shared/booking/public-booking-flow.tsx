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
  getPublicBookingSlots,
  type BookingCatalog,
  type BookingSlotList,
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
  staff_id: z.string().uuid(),
  resource_id: z.string().uuid().optional(),
  starts_at: z.string().min(1),
  display_name: z.string().trim().min(1).max(160),
  email: z.string().email(),
});

export function PublicBookingFlow({ publicSlug }: { publicSlug: string }) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingCatalog>();
  const [slots, setSlots] = useState<BookingSlotList["items"]>([]);
  const [token, setToken] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      location_id: "",
      staff_id: "",
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
      const result = await getPublicBookingSlots(publicSlug, {
        service_id: service,
        location_id: location,
        from: from.toISOString().slice(0, 10),
        to: to.toISOString().slice(0, 10),
      });
      setSlots(result.items);
      setProblem(undefined);
    } catch {
      setProblem(t("loadError"));
    }
  };
  const submit = form.handleSubmit(
    async ({ display_name, email, ...booking }) => {
      try {
        const created = await createPublicBookingAppointment(
          publicSlug,
          {
            ...booking,
            resource_id: booking.resource_id || null,
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
          <div>
            <Label htmlFor="booking-slot">{t("slot")}</Label>
            <NativeSelect
              id="booking-slot"
              {...form.register("starts_at")}
              onChange={(event) => {
                const slot = slots.find(
                  (x) => x.starts_at === event.target.value,
                );
                form.setValue("starts_at", event.target.value);
                if (slot) {
                  form.setValue("staff_id", slot.staff_id);
                  form.setValue("resource_id", slot.resource_id ?? undefined);
                }
              }}
            >
              <option value="">{t("choose")}</option>
              {slots.map((x) => (
                <option
                  key={`${x.starts_at}:${x.staff_id}`}
                  value={x.starts_at}
                >
                  {new Date(x.starts_at).toLocaleString()}
                </option>
              ))}
            </NativeSelect>
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
