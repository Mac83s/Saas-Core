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
