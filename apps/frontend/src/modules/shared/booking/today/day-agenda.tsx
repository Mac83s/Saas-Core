"use client";

import { useEffect, useId, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  getBookingQueue,
  listBookingAppointments,
  type BookingAppointment,
} from "@saas-core/api-client";
import { buttonVariants } from "@saas-core/ui/components/button";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { StatusBadge } from "../appointment-dialogs";
import { addDays, dateFormat, wallClock } from "../calendar-time";
import { visitName } from "../visit-name";

/** A day shows this many visits; the rest are a link to the calendar. */
const SHOWN = 8;

/**
 * „Dziś” of a company without a product dashboard (UX-022): today's and
 * tomorrow's visits — the whole team's for whoever plans visits, one's own
 * for everybody else — and the visits waiting for people. What the day holds
 * comes before what is left to set up.
 */
export function DayAgenda({
  access,
  timeZone,
}: {
  access: PanelAccess;
  timeZone: string;
}) {
  const t = useTranslations("Dashboard");
  const team = allows(access, { permission: "booking.appointment.manage" });
  const [today] = useState(() => wallClock(new Date(), timeZone).day);
  const [visits, setVisits] = useState<BookingAppointment[]>();
  const [waiting, setWaiting] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    listBookingAppointments({ from: today, to: addDays(today, 2), mine: !team })
      .then((items) => {
        if (live) setVisits(items.filter((item) => item.status !== "canceled"));
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    if (team)
      getBookingQueue()
        .then((items) => {
          if (live) setWaiting(items.length);
        })
        .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [team, today]);

  return (
    <PanelSection
      actions={
        waiting ? (
          <Link
            className={cn(buttonVariants({ variant: "outline" }), "w-fit")}
            href="/panel/calendar/queue"
          >
            {t("dayQueue", { count: waiting })}
          </Link>
        ) : null
      }
      title={t(team ? "dayTeam" : "dayMine")}
    >
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("dayFailed")}
        </p>
      ) : !visits ? (
        <div className="h-40 animate-pulse rounded-xl bg-muted">
          <span className="sr-only">{t("dayLoading")}</span>
        </div>
      ) : (
        // grid-cols-1 caps the column at the screen: a long line truncates
        // instead of widening the page on a phone.
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[today, addDays(today, 1)].map((day, index) => (
            <Day
              day={day}
              key={day}
              team={team}
              timeZone={timeZone}
              title={index === 0 ? "dayToday" : "dayTomorrow"}
              visits={visits.filter(
                (visit) => wallClock(visit.starts_at, timeZone).day === day,
              )}
            />
          ))}
        </div>
      )}
    </PanelSection>
  );
}

function Day({
  day,
  team,
  timeZone,
  title,
  visits,
}: {
  day: string;
  team: boolean;
  timeZone: string;
  title: "dayToday" | "dayTomorrow";
  visits: BookingAppointment[];
}) {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  const headingId = useId();
  const calendar = `/panel/calendar?view=day&date=${day}`;
  const date = dateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T12:00:00Z`));

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold" id={headingId}>
        {t(title, { date })}
      </h3>
      {visits.length ? (
        <ol className="flex flex-col gap-2">
          {visits.slice(0, SHOWN).map((visit) => (
            <li key={visit.id}>
              <Link
                className="flex items-start gap-3 rounded-lg border bg-card p-3 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                href={calendar}
              >
                {/* One unbreakable range: „08:00–09:00” never splits. */}
                <span className="font-medium whitespace-nowrap tabular-nums">
                  {dateFormat(locale, {
                    hour: "2-digit",
                    minute: "2-digit",
                    hourCycle: "h23",
                    timeZone,
                  }).formatRange(
                    new Date(visit.starts_at),
                    new Date(visit.ends_at),
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {visitName(visit)}
                  </span>
                  <span className="block truncate text-muted-foreground">
                    {[
                      visit.place ?? visit.location_name,
                      visit.service_name,
                      team ? visit.staff_name : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <StatusBadge status={visit.status} />
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">{t("dayNone")}</p>
      )}
      {visits.length > SHOWN ? (
        <Link className="text-sm text-primary underline" href={calendar}>
          {t("dayMore", { count: visits.length - SHOWN })}
        </Link>
      ) : null}
    </section>
  );
}
