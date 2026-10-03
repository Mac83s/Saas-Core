import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { NotificationBell } from "./notification-bell";

const { getNotificationInbox, markNotificationsRead } = vi.hoisted(() => ({
  getNotificationInbox: vi.fn(),
  markNotificationsRead: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getNotificationInbox,
  markNotificationsRead,
}));

const trialEnding = {
  id: "01a07000-0000-7000-8000-000000000001",
  kind: "billing.trial_ending",
  payload: { plan_name: "Witryna", ends_at: "2026-09-06" },
  severity: "warning" as const,
  created_at: "2026-09-05T10:00:00Z",
  read_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  getNotificationInbox.mockResolvedValue({ unread: 1, items: [trialEnding] });
});

afterEach(cleanup);

function renderBell() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <NotificationBell />
    </NextIntlClientProvider>,
  );
}

test("liczy nieprzeczytane i opisuje je zdaniem w języku czytelnika", async () => {
  const rendered = renderBell();

  const bell = await screen.findByRole("button", {
    name: "Powiadomienia, nieprzeczytane: 1",
  });
  fireEvent.click(bell);

  expect(
    await screen.findByText(
      "Okres próbny planu Witryna kończy się 2026-09-06. Po tej dacie pobierzemy pierwszą opłatę.",
    ),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("oznaczenie jako przeczytane gasi licznik", async () => {
  markNotificationsRead.mockResolvedValue({
    unread: 0,
    items: [{ ...trialEnding, read_at: "2026-09-05T11:00:00Z" }],
  });
  renderBell();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Powiadomienia, nieprzeczytane: 1",
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Oznacz wszystkie jako przeczytane",
    }),
  );

  await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledTimes(1));
  // The dialog hides the bell from the accessibility tree while it is open, so
  // the counter is checked where it is visible: nothing left to mark.
  await waitFor(() =>
    expect(
      screen.queryByRole("button", {
        name: "Oznacz wszystkie jako przeczytane",
      }),
    ).toBeNull(),
  );
});

test("pusta skrzynka nie krzyczy licznikiem", async () => {
  getNotificationInbox.mockResolvedValue({ unread: 0, items: [] });
  renderBell();

  fireEvent.click(await screen.findByRole("button", { name: "Powiadomienia" }));

  expect(await screen.findByText("Nie ma nic nowego.")).not.toBeNull();
});

test("wizyty w dzwonku: zdanie w strefie firmy i link do dnia w kalendarzu", async () => {
  const visit = (kind: string, extra: Record<string, unknown> = {}) => ({
    ...trialEnding,
    id: `01a07000-0000-7000-8000-${kind.length.toString().padStart(12, "0")}`,
    kind,
    severity: "info" as const,
    // 23:30 in Warsaw on 30 September is already 1 October's date there.
    payload: {
      appointment_id: "01a07000-0000-7000-8000-00000000000a",
      starts_at: "2026-09-30T22:30:00Z",
      timezone: "Europe/Warsaw",
      service_name: "Korekcja stada",
      ...extra,
    },
  });
  getNotificationInbox.mockResolvedValue({
    unread: 2,
    items: [
      visit("booking.assigned"),
      visit("booking.moved", { previous_starts_at: "2026-09-29T06:00:00Z" }),
    ],
  });
  renderBell();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Powiadomienia, nieprzeczytane: 2",
    }),
  );
  const assigned = await screen.findByRole("link", {
    name: "Przydzielono Cię do wizyty: Korekcja stada, 1 paź 2026, 00:30.",
  });
  expect(assigned.getAttribute("href")).toBe(
    "/panel/calendar?view=day&date=2026-10-01",
  );
  expect(
    screen.getByRole("link", {
      name: "Wizyta Korekcja stada z 29 wrz 2026, 08:00 jest teraz 1 paź 2026, 00:30.",
    }),
  ).not.toBeNull();
});

test("tłumaczenia w dzwonku: braki zlecenia i to, co czeka na decyzję", async () => {
  const notice = (kind: string, payload: Record<string, unknown>) => ({
    ...trialEnding,
    id: `01a07000-0000-7000-8000-${kind.length.toString().padStart(12, "0")}`,
    kind,
    severity: "info" as const,
    payload,
  });
  getNotificationInbox.mockResolvedValue({
    unread: 2,
    items: [
      notice("translation.job_problem", {
        job_id: "j",
        state: "partial",
        count: 5,
        written: 3,
      }),
      notice("translation.review_waiting", {
        count: 4,
        reasons: { review_mode: 4 },
      }),
      notice("translation.automation_paused", { reason: "monthly_limit" }),
    ],
  });
  renderBell();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Powiadomienia, nieprzeczytane: 2",
    }),
  );
  expect(
    await screen.findByText(
      "Tłumaczenie zakończone z brakami: przetłumaczono 3 z 5 pozycji.",
    ),
  ).not.toBeNull();
  expect(
    screen.getByText("4 tłumaczenia czekają na Twoją decyzję."),
  ).not.toBeNull();
  expect(
    screen.getByText(
      "Automatyczne tłumaczenie zmian wstrzymane: wykorzystano miesięczny limit automatu.",
    ),
  ).not.toBeNull();
});
