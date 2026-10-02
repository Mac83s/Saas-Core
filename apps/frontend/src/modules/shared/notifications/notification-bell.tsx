"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { BellIcon } from "lucide-react";

import {
  getNotificationInbox,
  markNotificationsRead,
  type AppNotification,
  type AppNotificationInbox,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";

import { Link } from "#i18n/navigation";

// How often the bell asks. Billing warnings arrive on a scheduler, so anything
// faster only costs requests; anything slower and somebody can miss the last
// day of a grace period while sitting in the panel.
const REFRESH_MS = 120_000;

export function NotificationBell() {
  const t = useTranslations("NotificationBell");
  const common = useTranslations("Common");
  const format = useFormatter();
  const [inbox, setInbox] = useState<AppNotificationInbox | undefined>(
    undefined,
  );
  const [open, setOpen] = useState(false);

  // A bell that cannot load is not worth an error on somebody's screen: it
  // stays quiet and tries again on the next tick.
  const load = useCallback(() => {
    getNotificationInbox()
      .then((value) => setInbox(value))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function markRead() {
    try {
      setInbox(await markNotificationsRead());
    } catch {
      /* left unread; the next load shows the truth */
    }
  }

  const unread = inbox?.unread ?? 0;
  const items = inbox?.items ?? [];

  return (
    <Dialog onOpenChange={setOpen} open={open}>
      <DialogTrigger
        render={
          <Button
            aria-label={
              unread > 0 ? t("openWithUnread", { count: unread }) : t("open")
            }
            className="relative"
            size="icon"
            variant="ghost"
          />
        }
      >
        <BellIcon aria-hidden="true" className="size-5" />
        {unread > 0 ? (
          <Badge
            aria-hidden="true"
            className="absolute -right-1 -top-1 min-w-5 justify-center px-1 py-0 text-[0.625rem]"
            variant="destructive"
          >
            {unread > 9 ? "9+" : unread}
          </Badge>
        ) : null}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        {items.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <>
            <ul className="max-h-96 divide-y overflow-y-auto">
              {items.map((item) => (
                <li
                  className={item.read_at ? "py-3" : "bg-muted/40 px-2 py-3"}
                  key={item.id}
                >
                  <p className="text-sm font-medium">
                    {calendarDay(item) ? (
                      <Link
                        className="hover:underline"
                        href={`/panel/calendar?view=day&date=${calendarDay(item)}`}
                        onClick={() => setOpen(false)}
                      >
                        {headline(item, t, format)}
                      </Link>
                    ) : (
                      headline(item, t, format)
                    )}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {format.dateTime(new Date(item.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </p>
                </li>
              ))}
            </ul>
            {unread > 0 ? (
              <Button
                className="self-start"
                onClick={() => void markRead()}
                size="sm"
                variant="outline"
              >
                {t("markAllRead")}
              </Button>
            ) : null}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// The sentence lives here, not in the database: the backend sends what happened
// and the facts, so one message reads Polish for one member and English for
// another, and a wording fix never needs a data migration.
function headline(
  item: AppNotification,
  t: ReturnType<typeof useTranslations<"NotificationBell">>,
  format: ReturnType<typeof useFormatter>,
): string {
  const payload = (item.payload ?? {}) as Record<string, unknown>;
  // A visit's time as the business keeps it, not as the reader's device does.
  const at = (value: unknown) =>
    value
      ? format.dateTime(new Date(String(value)), {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: String(payload.timezone || "UTC"),
        })
      : "";
  const values = {
    plan: String(payload.plan_name ?? ""),
    date: String(payload.ends_at ?? ""),
    farm: String(payload.farm_name ?? ""),
    count: Number(payload.count ?? 0),
    company: String(payload.company_name ?? ""),
    reason: String(payload.reason ?? ""),
    service: String(payload.service_name ?? ""),
    written: Number(payload.written ?? 0),
    when: at(payload.starts_at),
    before: at(payload.previous_starts_at),
  };
  switch (item.kind) {
    case "billing.trial_ending":
      return t("billingTrialEnding", values);
    case "billing.grace_ending":
      return t("billingGraceEnding", values);
    case "farms.herd_review":
      return t("farmsHerdReview", values);
    case "farms.health_corrected":
      return t("farmsHealthCorrected", values);
    case "booking.assigned":
      return t("bookingAssigned", values);
    case "booking.unassigned":
      return t("bookingUnassigned", values);
    case "booking.moved":
      return t("bookingMoved", values);
    case "booking.canceled":
      return t("bookingCanceled", values);
    case "translation.job_problem":
      return t("translationJobProblem", values);
    case "translation.review_waiting":
      return t("translationReviewWaiting", values);
    default:
      return t("unknown");
  }
}

/** The calendar day a visit's notice opens, in the business's own zone. */
function calendarDay(item: AppNotification): string | null {
  if (!item.kind.startsWith("booking.")) return null;
  const payload = (item.payload ?? {}) as Record<string, unknown>;
  if (!payload.starts_at) return null;
  // en-CA writes a date as YYYY-MM-DD, the calendar's own address format.
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: String(payload.timezone || "UTC"),
  }).format(new Date(String(payload.starts_at)));
}
