"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  cancelSelfServiceBooking,
  getSelfServiceBooking,
  rescheduleSelfServiceBooking,
  type BookingPublicAppointment,
  type BookingPublicQuote,
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

import { QuoteSummary } from "./quote-summary";
import { TransferDetails } from "./transfer-details";

const schema = z.object({ starts_at: z.string().min(1) });

export function SelfServiceBooking({ token }: { token: string }) {
  const t = useTranslations("BookingSelfService");
  const locale = useLocale();
  const [appointment, setAppointment] = useState<BookingPublicAppointment>();
  const [problem, setProblem] = useState<string>();
  // The price of the time just asked for, when it is another one than the
  // visit has: shown first, taken with the next click (ADR-072 §7).
  const [offered, setOffered] = useState<{
    startsAt: string;
    quote: BookingPublicQuote;
  }>();
  // The booking's own terms (B4); a booking read from an older server has
  // none and keeps both actions, as before.
  const terms = appointment?.self_service ?? {
    reschedule: true,
    cancel: true,
    until: null,
  };
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
    const startsAt = new Date(starts_at).toISOString();
    try {
      const value = await rescheduleSelfServiceBooking(
        token,
        startsAt,
        crypto.randomUUID(),
        offered?.startsAt === startsAt ? offered.quote.digest : undefined,
      );
      setAppointment(value);
      setOffered(undefined);
      setProblem(undefined);
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "quote_changed"
      ) {
        const detail = error.problem.detail as {
          quote?: BookingPublicQuote | null;
        };
        if (detail.quote) {
          setOffered({ startsAt, quote: detail.quote });
          setProblem(undefined);
          return;
        }
      }
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
              <p className="text-sm">{appointment.location_name}</p>
              {appointment.team_name ? (
                <p className="text-sm">
                  {t("chosenTeam", { team: appointment.team_name })}
                </p>
              ) : null}
              {appointment.person_name ? (
                <p className="text-sm">
                  {t("seenBy", { name: appointment.person_name })}
                </p>
              ) : null}
            </div>
            {/* The booking waits for this transfer before it is confirmed. */}
            {appointment.payment ? (
              <TransferDetails
                payment={appointment.payment}
                zone={appointment.timezone}
              />
            ) : null}
            {appointment.quote ? (
              <QuoteSummary quote={appointment.quote} />
            ) : null}
            {appointment.status === "confirmed" ||
            appointment.status === "pending_payment" ? (
              <>
                {/* What the link may still do: the booking's own terms (B4). */}
                {terms.reschedule ? (
                  <form className="space-y-3" onSubmit={reschedule}>
                    <Label htmlFor="self-service-start">{t("newTime")}</Label>
                    <Input
                      id="self-service-start"
                      type="datetime-local"
                      {...form.register("starts_at", {
                        onChange: () => setOffered(undefined),
                      })}
                    />
                    {offered ? (
                      <div className="space-y-2" role="status">
                        <p className="text-sm">{t("newPrice")}</p>
                        <QuoteSummary quote={offered.quote} />
                      </div>
                    ) : null}
                    <Button
                      disabled={form.formState.isSubmitting}
                      type="submit"
                    >
                      {offered ? t("rescheduleAtPrice") : t("reschedule")}
                    </Button>
                  </form>
                ) : null}
                {terms.cancel ? (
                  <Button onClick={() => void cancel()} variant="destructive">
                    {t("cancel")}
                  </Button>
                ) : null}
                {appointment.self_service ? (
                  <p className="text-sm text-muted-foreground">
                    {terms.until
                      ? t(terms.reschedule ? "changesUntil" : "cancelUntil", {
                          when: new Intl.DateTimeFormat(locale, {
                            dateStyle: "full",
                            timeStyle: "short",
                            timeZone: appointment.timezone,
                          }).format(new Date(terms.until)),
                        })
                      : t("contactCompany")}
                  </p>
                ) : null}
              </>
            ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
