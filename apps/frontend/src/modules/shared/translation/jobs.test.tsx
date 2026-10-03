import axe from "axe-core";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type TranslationJob,
  type TranslationJobDetail as JobDetail,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { TranslationJobDetail } from "./job-detail";
import { TranslationJobsBar } from "./jobs-bar";
import { TranslationJobsPanel } from "./jobs-panel";

const { api } = vi.hoisted(() => ({
  api: {
    listTranslationJobs: vi.fn(),
    getTranslationJob: vi.fn(),
    cancelTranslationJob: vi.fn(),
    revertTranslationJob: vi.fn(),
    listTranslationReview: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/sites/translations/jobs",
}));
// The eyebrow reads the menu, which these pages do not test.
vi.mock("#components/panel/panel-eyebrow", () => ({
  PanelEyebrow: ({ fallback }: { fallback: string }) => <p>{fallback}</p>,
}));

const JOB = "0199f0a0-0000-7000-8000-0000000000d1";
const HOME = "0199f0a0-0000-7000-8000-0000000000a1";
const SITE = "0199f0a0-0000-7000-8000-000000000001";

function item(
  overrides: Partial<JobDetail["items"][number]> = {},
): JobDetail["items"][number] {
  return {
    id: "0199f0a0-0000-7000-8000-0000000000e1",
    source_key: "sites.page",
    object_id: HOME,
    locale: "en",
    scope: SITE,
    label: "Strona główna",
    state: "written",
    quoted_characters: 800,
    delivered_characters: 790,
    outcomes: [{ state: "live", reason: null, keys: 12 }],
    error_code: "",
    ...overrides,
  };
}

function job(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: JOB,
    state: "succeeded",
    trigger: "click",
    billing: "credits",
    units: 2,
    credits: 4,
    error_code: "",
    next_attempt_at: "2026-10-03T12:00:00Z",
    created_at: "2026-10-03T12:00:00Z",
    started_at: "2026-10-03T12:00:05Z",
    finished_at: "2026-10-03T12:01:00Z",
    reverted_at: null,
    confirmation_required: false,
    revertable: true,
    parts: [
      {
        index: 0,
        units: 2,
        state: "settled",
        deadline_at: "2026-10-06T12:00:05Z",
        delivered_characters: 1500,
        settled_units: 2,
        settled_credits: 4,
        reserved_credits: 4,
      },
    ],
    items: [
      item(),
      item({
        id: "0199f0a0-0000-7000-8000-0000000000e2",
        locale: "de",
        outcomes: [{ state: "pending", reason: "overwrites_human", keys: 3 }],
      }),
    ],
    ...overrides,
  };
}

const RUNNING = job({
  state: "running",
  finished_at: null,
  revertable: false,
  parts: [{ ...job().parts[0]!, state: "running", settled_credits: 0 }],
  items: [
    item(),
    item({
      id: "0199f0a0-0000-7000-8000-0000000000e2",
      locale: "de",
      state: "queued",
      delivered_characters: 0,
      outcomes: [],
    }),
  ],
});

function page(items: TranslationJob[]) {
  return { items, next_cursor: null };
}

function view(children: ReactNode, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      {children}
    </NextIntlClientProvider>,
  );
}

async function expectNoAxeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(
    results.violations.map((violation) => violation.id),
    JSON.stringify(results.violations, null, 2),
  ).toEqual([]);
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listTranslationReview.mockResolvedValue({
    items: [],
    count: 0,
    next_cursor: null,
  });
});
afterEach(() => {
  vi.useRealTimers();
});

test("the bar draws nothing while nothing runs, and nothing where there is no engine", async () => {
  api.listTranslationJobs.mockResolvedValueOnce(page([]));
  const idle = view(<TranslationJobsBar />);
  await waitFor(() =>
    expect(api.listTranslationJobs).toHaveBeenCalledWith({
      active: true,
      limit: 5,
    }),
  );
  expect(idle.container.textContent).toBe("");
  idle.unmount();

  api.listTranslationJobs.mockRejectedValueOnce(new Error("404"));
  const absent = view(<TranslationJobsBar />);
  await waitFor(() => expect(api.listTranslationJobs).toHaveBeenCalledTimes(2));
  expect(absent.container.textContent).toBe("");
});

test("the bar follows a running job, says why it waits and tells the list when it ends", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-10-03T12:00:30Z"));
  api.listTranslationJobs.mockResolvedValue(
    page([{ ...RUNNING, next_attempt_at: "2026-10-03T13:30:00Z" }]),
  );
  const finished = vi.fn();
  const { container } = view(<TranslationJobsBar onFinished={finished} />);

  const bar = await screen.findByRole("region", { name: "Tłumaczenia w toku" });
  expect(bar.textContent).toContain("Tłumaczenie w toku: 1 z 2");
  const progress = within(bar).getByRole("progressbar");
  expect(progress.getAttribute("aria-valuenow")).toBe("1");
  expect(progress.getAttribute("aria-valuemax")).toBe("2");
  // The model pool is busy: the job says when it comes back.
  expect(bar.textContent).toContain(
    "Czeka na wolne miejsce u dostawcy AI — wznowi się 3 paź 2026, 15:30.",
  );
  expect(within(bar).getByRole("link", { name: /^Szczegóły/ })).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/translations/jobs/${JOB}`),
  );
  await expectNoAxeViolations(container);

  // It ends: the bar goes and the list is told to read again.
  api.listTranslationJobs.mockResolvedValue(page([]));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4100);
  });
  await waitFor(() => expect(finished).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("region")).toBeNull();
  // Nothing runs: nothing more is asked.
  const asked = api.listTranslationJobs.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(api.listTranslationJobs).toHaveBeenCalledTimes(asked);
});

test("„Zadania” lists the orders with their state, progress and credits; the filter is the server's", async () => {
  api.listTranslationJobs.mockResolvedValue(
    page([
      job(),
      job({
        id: "0199f0a0-0000-7000-8000-0000000000d2",
        trigger: "automatic",
        state: "partial",
        reverted_at: "2026-10-03T13:00:00Z",
        created_at: "2026-10-02T09:00:00Z",
      }),
    ]),
  );
  const { container } = view(<TranslationJobsPanel />);

  const table = await screen.findByRole("table", { name: "Zadania tłumaczeń" });
  const [first, second] = within(table).getAllByRole("row").slice(1);
  expect(first!.textContent).toContain("3 paź 2026, 14:00");
  expect(first!.textContent).toContain("Zlecenie");
  expect(first!.textContent).toContain("Gotowe");
  expect(first!.textContent).toContain("2 z 2");
  expect(
    within(first!).getByRole("link", { name: "Szczegóły" }),
  ).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/translations/jobs/${JOB}`),
  );
  expect(second!.textContent).toContain("Automat zmian");
  expect(second!.textContent).toContain("Gotowe częściowo");
  expect(second!.textContent).toContain("Cofnięte");
  expect(api.listTranslationJobs).toHaveBeenCalledWith({ limit: 20 });
  // The third view of the same menu entry.
  expect(await screen.findByRole("link", { name: "Zadania" })).toHaveProperty(
    "href",
    expect.stringContaining("/panel/sites/translations/jobs"),
  );
  await expectNoAxeViolations(container);

  api.listTranslationJobs.mockResolvedValue(page([]));
  fireEvent.change(screen.getByLabelText("Stan"), {
    target: { value: "active" },
  });
  await waitFor(() =>
    expect(api.listTranslationJobs).toHaveBeenLastCalledWith({
      limit: 20,
      active: true,
    }),
  );
});

test("„Zadania”: empty, failed and English", async () => {
  api.listTranslationJobs.mockResolvedValueOnce(page([]));
  const empty = view(<TranslationJobsPanel />, "en");
  expect(
    await screen.findByText("No translation has been ordered yet."),
  ).toBeTruthy();
  await expectNoAxeViolations(empty.container);
  empty.unmount();

  api.listTranslationJobs.mockRejectedValueOnce(new Error("offline"));
  view(<TranslationJobsPanel />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Nie udało się wczytać zadań tłumaczeń.",
  );
  api.listTranslationJobs.mockResolvedValueOnce(page([job()]));
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(await screen.findByText("Gotowe")).toBeTruthy();
});

test("a job's detail names what it translated, how each pair ended and what each part cost", async () => {
  api.getTranslationJob.mockResolvedValue(job());
  const { container } = view(<TranslationJobDetail jobId={JOB} />);

  expect(
    await screen.findByRole("heading", {
      level: 1,
      name: "Zadanie tłumaczenia",
    }),
  ).toBeTruthy();
  expect(api.getTranslationJob).toHaveBeenCalledWith(JOB, { labels: true });
  expect(screen.getByRole("link", { name: "Zadania" })).toHaveProperty(
    "href",
    expect.stringContaining("/panel/sites/translations/jobs"),
  );
  const items = await screen.findByRole("table", { name: "Pozycje zadania" });
  const [english, german] = within(items).getAllByRole("row").slice(1);
  expect(english!.textContent).toContain("Strona główna");
  expect(english!.textContent).toContain("Podstrona");
  expect(english!.textContent).toContain("English");
  expect(english!.textContent).toContain("Przetłumaczone");
  expect(english!.textContent).toContain("Opublikowane");
  expect(english!.textContent).toContain("790 z 800");
  expect(german!.textContent).toContain(
    "Czeka na akceptację — Zmieniłoby Twoje poprawki",
  );
  expect(within(english!).getByRole("link", { name: "Otwórz" })).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/pages/${HOME}?language=en`),
  );
  const parts = screen.getByRole("table", { name: "Części zadania" });
  const [part] = within(parts).getAllByRole("row").slice(1);
  expect(part!.textContent).toContain("Część 1");
  expect(part!.textContent).toContain("Rozliczona");
  expect(
    screen.getByText("wycena 4 · zarezerwowane teraz 0 · rozliczone 4"),
  ).toBeTruthy();
  // Ended: nothing to stop, and no progress bar.
  expect(
    screen.queryByRole("button", { name: "Zatrzymaj zadanie" }),
  ).toBeNull();
  expect(screen.queryByRole("progressbar")).toBeNull();
  await expectNoAxeViolations(container);
});

test("the last job is taken back after a question; the refusal of a person-only decision is said", async () => {
  api.getTranslationJob.mockResolvedValue(job());
  view(<TranslationJobDetail jobId={JOB} />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Cofnij ostatnie zadanie" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Cofnąć to zadanie?",
  });
  expect(dialog.textContent).toContain("Kredyty nie wracają");
  expect(api.revertTranslationJob).not.toHaveBeenCalled();

  api.revertTranslationJob.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Forbidden",
      status: 403,
      code: "person_required",
      detail: "",
    } as ConstructorParameters<typeof ApiProblemError>[0]),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Cofnij zadanie" }),
  );
  expect((await within(dialog).findByRole("alert")).textContent).toContain(
    "Tę decyzję podejmuje osoba",
  );

  api.revertTranslationJob.mockResolvedValueOnce(job());
  api.getTranslationJob.mockResolvedValue(
    job({ reverted_at: "2026-10-03T13:00:00Z", revertable: false }),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Cofnij zadanie" }),
  );
  await waitFor(() =>
    expect(api.revertTranslationJob).toHaveBeenLastCalledWith(
      JOB,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText(
      "Zadanie cofnięte: teksty wróciły do stanu sprzed niego.",
    ),
  ).toBeTruthy();
  expect(await screen.findByText("Cofnięte")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Cofnij ostatnie zadanie" }),
  ).toBeNull();
});

test("a running job shows its progress and can be stopped; a job that is gone says so", async () => {
  api.getTranslationJob.mockResolvedValue(RUNNING);
  const running = view(<TranslationJobDetail jobId={JOB} />, "en");

  const progress = await screen.findByRole("progressbar");
  expect(progress.getAttribute("aria-valuenow")).toBe("1");
  // Running jobs cannot be taken back yet.
  expect(
    screen.queryByRole("button", { name: "Take back the last job" }),
  ).toBeNull();
  await expectNoAxeViolations(running.container);
  fireEvent.click(screen.getByRole("button", { name: "Stop the job" }));
  const dialog = await screen.findByRole("dialog", { name: "Stop this job?" });
  api.cancelTranslationJob.mockResolvedValueOnce(RUNNING);
  api.getTranslationJob.mockResolvedValue(
    job({ state: "canceled", error_code: "canceled", revertable: false }),
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Stop the job" }));
  await waitFor(() =>
    expect(api.cancelTranslationJob).toHaveBeenCalledWith(
      JOB,
      expect.any(String),
    ),
  );
  expect(await screen.findByText("The job has been stopped.")).toBeTruthy();
  expect(await screen.findByText("Stopped")).toBeTruthy();
  running.unmount();

  api.getTranslationJob.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Not found",
      status: 404,
      code: "not_found",
      detail: "",
    } as ConstructorParameters<typeof ApiProblemError>[0]),
  );
  view(<TranslationJobDetail jobId={JOB} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Nie ma takiego zadania.",
  );
});
