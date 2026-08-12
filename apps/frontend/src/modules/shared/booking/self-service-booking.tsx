"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  cancelSelfServiceBooking,
  getSelfServiceBooking,
  rescheduleSelfServiceBooking,
  type BookingAppointment,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
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

const schema = z.object({ starts_at: z.string().min(1) });

export function SelfServiceBooking({ token }: { token: string }) {
  const t = useTranslations("BookingSelfService");
  const [appointment, setAppointment] = useState<BookingAppointment>();
  const [problem, setProblem] = useState<string>();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { starts_at: "" },
  });

  useEffect(() => {
    void getSelfServiceBooking(token)
      .then(setAppointment)
      .catch(() => setProblem(t("notFound")));
  }, [t, token]);

  const reschedule = form.handleSubmit(async ({ starts_at }) => {
    try {
      const value = await rescheduleSelfServiceBooking(
        token,
        new Date(starts_at).toISOString(),
        crypto.randomUUID(),
      );
      setAppointment(value);
      setProblem(undefined);
    } catch {
      setProblem(t("rescheduleError"));
    }
  });

  const cancel = async () => {
    try {
      const value = await cancelSelfServiceBooking(token, crypto.randomUUID());
      setAppointment(value);
      setProblem(undefined);
    } catch {
      setProblem(t("cancelError"));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        {appointment ? (
          <>
            <div className="rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <p className="font-medium">{appointment.service_name}</p>
                <Badge variant="outline">{t(appointment.status)}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {new Intl.DateTimeFormat(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                  timeZone: appointment.timezone,
                }).format(new Date(appointment.starts_at))}
              </p>
              <p className="text-sm">
                {appointment.staff_name} · {appointment.location_name}
              </p>
            </div>
            {appointment.status === "confirmed" ? (
              <>
                <form className="space-y-3" onSubmit={reschedule}>
                  <Label htmlFor="self-service-start">{t("newTime")}</Label>
                  <Input
                    id="self-service-start"
                    type="datetime-local"
                    {...form.register("starts_at")}
                  />
                  <Button disabled={form.formState.isSubmitting} type="submit">
                    {t("reschedule")}
                  </Button>
                </form>
                <Button onClick={() => void cancel()} variant="destructive">
                  {t("cancel")}
                </Button>
              </>
            ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
