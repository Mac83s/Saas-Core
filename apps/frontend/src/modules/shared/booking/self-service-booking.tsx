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
  moveSelfServiceStay,
  previewSelfServiceStayMove,
  rescheduleSelfServiceBooking,
  type BookingPublicAppointment,
  type BookingPublicQuote,
  type BookingPublicStayPlan,
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

import { refusalOf, useStayHours, useStayWhen } from "./public-booking-parts";
import { QuoteSummary } from "./quote-summary";
import { TransferDetails } from "./transfer-details";

const schema = z.object({ starts_at: z.string().min(1) });

/**
 * A stay is moved by its dates (ADR-072, phase 5): the customer names the
 * new days, the server says whether they fit and at what price, and only
 * then the stay moves — never to a price the customer was not shown.
 */
function StayMove({
  appointment,
  onMoved,
  token,
}: {
  appointment: BookingPublicAppointment;
  onMoved: (moved: BookingPublicAppointment) => void;
  token: string;
}) {
  const t = useTranslations("BookingSelfService");
  const refused = useTranslations("PublicBooking");
  const stayWhen = useStayWhen();
  const unit = appointment.range_unit === "day" ? "day" : "night";
  const [dates, setDates] = useState({ start_date: "", end_date: "" });
  // The plan of the dates typed now; other dates are checked again.
  const [plan, setPlan] = useState<BookingPublicStayPlan>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const change = (field: "start_date" | "end_date", value: string) => {
    setDates({ ...dates, [field]: value });
    setPlan(undefined);
    setProblem(undefined);
  };
  const check = async () => {
    setBusy(true);
    try {
      setPlan(await previewSelfServiceStayMove(token, dates));
      setProblem(undefined);
    } catch (error) {
      setProblem(
        refused("stayRefused", { reason: refusalOf(error), count: 0 }),
      );
    } finally {
      setBusy(false);
    }
  };
  const move = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      onMoved(
        await moveSelfServiceStay(
          token,
          dates,
          crypto.randomUUID(),
          plan.quote?.digest,
        ),
      );
      setDates({ start_date: "", end_date: "" });
      setPlan(undefined);
      setProblem(undefined);
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "quote_changed"
      ) {
        // Another price by now: shown first, taken with the next click.
        const detail = error.problem.detail as {
          quote?: BookingPublicQuote | null;
        };
        setPlan({ ...plan, quote: detail.quote ?? null });
        setProblem(t("newPrice"));
        return;
      }
      setPlan(undefined);
      setProblem(t("stayMoveError"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-medium">{t("newTime")}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="self-service-stay-start">
            {t("stayStart", { unit })}
          </Label>
          <Input
            id="self-service-stay-start"
            onChange={(event) => change("start_date", event.target.value)}
            type="date"
            value={dates.start_date}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="self-service-stay-end">
            {t("stayEnd", { unit })}
          </Label>
          <Input
            id="self-service-stay-end"
            min={dates.start_date || undefined}
            onChange={(event) => change("end_date", event.target.value)}
            type="date"
            value={dates.end_date}
          />
        </div>
      </div>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      {plan ? (
        <div className="space-y-2" role="status">
          <p className="text-sm">
            {t("stayPlan", {
              when: stayWhen({ ...plan, timezone: appointment.timezone }),
            })}
          </p>
          {/* Only a confirmed stay moves: what was paid stays paid, so the
              offer's terms of paying ahead are no instruction here. */}
          {plan.quote ? <QuoteSummary quote={plan.quote} settled /> : null}
        </div>
      ) : null}
      {plan ? (
        <Button disabled={busy} onClick={() => void move()} type="button">
          {t("stayMove")}
        </Button>
      ) : (
        <Button
          disabled={busy || !dates.start_date || !dates.end_date}
          onClick={() => void check()}
          type="button"
          variant="outline"
        >
          {t("stayCheck")}
        </Button>
      )}
    </fieldset>
  );
}

export function SelfServiceBooking({ token }: { token: string }) {
  const t = useTranslations("BookingSelfService");
  const locale = useLocale();
  const [appointment, setAppointment] = useState<BookingPublicAppointment>();
  const [problem, setProblem] = useState<string>();
  const stayWhen = useStayWhen();
  const stayHours = useStayHours();
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
  // What comes back of what the customer paid: the server's numbers, by
  // the terms the booking was made under (ADR-073 §8).
  const settlement = appointment?.settlement;
  const money = (minor: number, currency: string) =>
    new Intl.NumberFormat(locale, { style: "currency", currency }).format(
      minor / 100,
    );
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
              {/* A stay is told by its days and its unit, a visit by its time. */}
              {appointment.time_model === "range" ? (
                <>
                  <p className="mt-1 text-sm font-medium">
                    {stayWhen(appointment)}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {stayHours(appointment)}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">
                  {new Intl.DateTimeFormat(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: appointment.timezone,
                  }).format(new Date(appointment.starts_at))}
                </p>
              )}
              <p className="text-sm">
                {appointment.unit_name
                  ? `${appointment.unit_name} · ${appointment.location_name}`
                  : appointment.location_name}
              </p>
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
            {/* The booking waits for this transfer before it is confirmed,
                or the rest of its price is due by one. */}
            {appointment.payment ? (
              <TransferDetails
                payment={appointment.payment}
                zone={appointment.timezone}
              />
            ) : null}
            {appointment.quote ? (
              <QuoteSummary
                quote={appointment.quote}
                settled={
                  appointment.status !== "pending_payment" &&
                  appointment.status !== "pending_request"
                }
              />
            ) : null}
            {appointment.status === "canceled" && settlement ? (
              <p className="text-sm" role="status">
                {t("canceledGivesBack", {
                  paid: money(settlement.paid_minor, settlement.currency),
                  refund: money(settlement.refund_minor, settlement.currency),
                })}
              </p>
            ) : null}
            {/* A request waits for the company's answer until a date. */}
            {appointment.status === "pending_request" &&
            appointment.hold_expires_at ? (
              <p className="text-sm" role="note">
                {t("answerBy", {
                  when: new Intl.DateTimeFormat(locale, {
                    dateStyle: "full",
                    timeStyle: "short",
                    timeZone: appointment.timezone,
                  }).format(new Date(appointment.hold_expires_at)),
                })}
              </p>
            ) : null}
            {appointment.status === "confirmed" ||
            appointment.status === "pending_payment" ||
            appointment.status === "pending_request" ? (
              <>
                {/* What the link may still do: the booking's own terms (B4). */}
                {terms.reschedule && appointment.time_model === "range" ? (
                  <StayMove
                    appointment={appointment}
                    onMoved={(moved) => {
                      setAppointment(moved);
                      setProblem(undefined);
                    }}
                    token={token}
                  />
                ) : terms.reschedule ? (
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
                        {/* A confirmed visit: nothing is paid ahead anew. */}
                        <QuoteSummary quote={offered.quote} settled />
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
                {/* Said before the click: giving up settles the money. */}
                {terms.cancel && settlement ? (
                  <p className="text-sm" role="note">
                    {t("cancelGivesBack", {
                      paid: money(settlement.paid_minor, settlement.currency),
                      refund: money(
                        settlement.refund_minor,
                        settlement.currency,
                      ),
                    })}
                  </p>
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
