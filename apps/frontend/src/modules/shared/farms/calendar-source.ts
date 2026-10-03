import { listRegisterVisits } from "@saas-core/api-client";

import type { CalendarSource } from "#lib/calendar-sources";

/**
 * The companies' visits to the keeper's farms, on the keeper's own calendar
 * (UX-078). A company's calendar has no such rows: they are written into the
 * keeper's register only, so for anybody else the list is simply empty.
 */
export const farmVisitsSource: CalendarSource = {
  key: "farms.visits",
  labelKey: "Farms.calendarVisit",
  module: "shared.farms",
  permission: "farms.read",
  load: async (from, to) =>
    (await listRegisterVisits({ from, to })).map((visit) => ({
      id: visit.id,
      at: visit.occurred_on ? null : visit.scheduled_for,
      day: visit.occurred_on,
      // Whose visit it is, then where: „Korekcja Racic Test · Gospodarstwo Kowalski”.
      title: [visit.company_name, visit.farm_name].filter(Boolean).join(" · "),
      detail: visit.summary,
      status: visit.status as "planned" | "done" | "canceled",
      href: `/panel/farms/${visit.farm_id}`,
    })),
};
