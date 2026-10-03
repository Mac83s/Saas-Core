import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import type { SessionSummary } from "@saas-core/api-client";
import { SessionManager } from "./session-controls";

const { api, router } = vi.hoisted(() => ({
  api: {
    listSessions: vi.fn(),
    revokeSession: vi.fn(),
    revokeOtherSessions: vi.fn(),
  },
  router: { replace: vi.fn(), refresh: vi.fn() },
}));

vi.mock("#i18n/navigation", () => ({ useRouter: () => router }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const current: SessionSummary = {
  id: "019ff20d-a000-7000-8000-000000000051",
  device_label: "Chrome on Linux",
  created_at: "2026-09-20T08:00:00Z",
  last_seen_at: "2026-09-28T08:00:00Z",
  expires_at: "2026-10-20T08:00:00Z",
  current: true,
};
const phone: SessionSummary = {
  id: "019ff20d-a000-7000-8000-000000000052",
  device_label: "Safari on iPhone",
  created_at: "2026-09-10T08:00:00Z",
  last_seen_at: "2026-09-12T18:30:00Z",
  expires_at: "2026-10-10T08:00:00Z",
  current: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listSessions.mockResolvedValue([current, phone]);
  api.revokeSession.mockResolvedValue(undefined);
});

afterEach(cleanup);

function renderManager(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SessionManager />
    </NextIntlClientProvider>,
  );
}

async function expectAccessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

test.each([
  ["pl", "Aktywne urządzenia", "Ta sesja"],
  ["en", "Active devices", "This session"],
] as const)(
  "sesje są listą, a bieżące urządzenie jest oznaczone (%s)",
  async (locale, caption, thisDevice) => {
    const { container } = renderManager(locale);

    const table = await screen.findByRole("table", { name: caption });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText("Chrome on Linux")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(thisDevice)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Safari on iPhone")).toBeInTheDocument();
    expect(within(rows[2]!).queryByText(thisDevice)).toBeNull();

    await expectAccessible(container);
  },
);

test("wylogowanie innego urządzenia unieważnia jego sesję i odświeża listę", async () => {
  renderManager();
  await screen.findByRole("table", { name: "Aktywne urządzenia" });
  api.listSessions.mockResolvedValue([current]);

  fireEvent.click(
    screen.getByRole("button", { name: "Działania: Safari on iPhone" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Wyloguj" }));

  await waitFor(() => expect(api.revokeSession).toHaveBeenCalledWith(phone.id));
  await waitFor(() =>
    expect(screen.queryByText("Safari on iPhone")).toBeNull(),
  );
  expect(api.listSessions).toHaveBeenCalledTimes(2);
  expect(router.replace).not.toHaveBeenCalled();
});

test("wylogowanie bieżącej sesji prowadzi do logowania", async () => {
  renderManager("en");
  await screen.findByRole("table", { name: "Active devices" });

  fireEvent.click(
    screen.getByRole("button", { name: "Actions: Chrome on Linux" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Log out" }));

  await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  expect(api.revokeSession).toHaveBeenCalledWith(current.id);
  expect(router.refresh).toHaveBeenCalled();
});

test("bez sesji mówi, że nie ma aktywnych urządzeń", async () => {
  api.listSessions.mockResolvedValue([]);
  renderManager();

  expect(await screen.findByText("Brak aktywnych sesji.")).toBeInTheDocument();
});

test("czytelne nazwy, powtórzenia w jednym wierszu i wylogowanie pozostałych (UX-054)", async () => {
  const chrome =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36";
  api.listSessions.mockResolvedValue([
    current,
    ...[1, 2, 3].map((n) => ({
      ...phone,
      id: `019ff20d-a000-7000-8000-00000000006${n}`,
      device_label: chrome,
      last_seen_at: `2026-09-2${n}T08:00:00Z`,
    })),
    {
      ...phone,
      id: "019ff20d-a000-7000-8000-000000000070",
      device_label: "node",
    },
  ]);
  api.revokeOtherSessions.mockResolvedValue(4);
  renderManager();

  expect(await screen.findByText("Chrome 154 · Windows")).not.toBeNull();
  expect(screen.getByText("3 sesje")).not.toBeNull();
  expect(screen.getByText("Skrypt / API")).not.toBeNull();
  expect(screen.queryByText(/Mozilla/)).toBeNull();

  fireEvent.click(
    screen.getByRole("button", { name: "Wyloguj pozostałe urządzenia" }),
  );
  await waitFor(() => expect(api.revokeOtherSessions).toHaveBeenCalledOnce());
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Wylogowano 4 inne sesje.",
  );
});
