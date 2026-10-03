import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type TranslationReviewItem,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { TranslationReviewPanel } from "./review-panel";

const { api } = vi.hoisted(() => ({
  api: { listTranslationReview: vi.fn(), decideTranslationReview: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/sites/translations/review",
}));
// The eyebrow reads the menu, which this page does not test.
vi.mock("#components/panel/panel-eyebrow", () => ({
  PanelEyebrow: ({ fallback }: { fallback: string }) => <p>{fallback}</p>,
}));

const HOME = "0199f0a0-0000-7000-8000-0000000000a1";
const SITE = "0199f0a0-0000-7000-8000-000000000001";

function item(
  overrides: Partial<TranslationReviewItem> = {},
): TranslationReviewItem {
  return {
    id: "0199f0a0-0000-7000-8000-0000000000b1",
    version: 1,
    job_id: null,
    source_key: "sites.page",
    object_id: HOME,
    locale: "en",
    reason: "overwrites_human",
    keys: 2,
    acceptable: true,
    state: "open",
    created_at: "2026-10-03T12:11:49Z",
    label: "Strona główna",
    scope: SITE,
    ...overrides,
  };
}

const CARD = item({
  id: "0199f0a0-0000-7000-8000-0000000000b2",
  source_key: "profiles.public_profile",
  object_id: "0199f0a0-0000-7000-8000-0000000000c1",
  locale: "de",
  reason: "review_mode",
  keys: 1,
  label: "Studio Testowe",
  scope: "",
});
const REFUSED = item({
  id: "0199f0a0-0000-7000-8000-0000000000b3",
  source_key: "sites.entry",
  object_id: "0199f0a0-0000-7000-8000-0000000000e1",
  locale: "de",
  reason: "qa_failed",
  acceptable: false,
  label: "Jak dbać o włosy zimą",
});

function page(items: TranslationReviewItem[], count = items.length) {
  return { items, count, next_cursor: null };
}

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <TranslationReviewPanel />
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
  api.listTranslationReview.mockResolvedValue(page([item(), CARD, REFUSED]));
});

test("lists what waits with its name, kind, language, reason and the way to it", async () => {
  const { container } = view();

  const table = await screen.findByRole("table", {
    name: "Tłumaczenia czekające na decyzję",
  });
  const [home, card, refused] = within(table).getAllByRole("row").slice(1);
  expect(within(home!).getByText("Strona główna")).toBeTruthy();
  expect(within(home!).getByText("Podstrona")).toBeTruthy();
  expect(within(home!).getByText("English")).toBeTruthy();
  expect(within(home!).getByText("Zmieniłoby Twoje poprawki")).toBeTruthy();
  expect(within(card!).getByText("Wizytówka")).toBeTruthy();
  expect(
    within(card!).getByText("Firma akceptuje tłumaczenia przed publikacją"),
  ).toBeTruthy();
  // Nothing to accept: no mark, no „Zaakceptuj” — the way to translate by hand.
  expect(within(refused!).queryByRole("checkbox")).toBeNull();
  expect(
    within(refused!).queryByRole("button", { name: "Zaakceptuj i opublikuj" }),
  ).toBeNull();
  expect(within(refused!).getByRole("link", { name: "Otwórz" })).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/blog?site=${SITE}`),
  );
  // The tab carries everything that waits.
  expect(
    screen.getByRole("link", { name: "Do akceptacji (3)" }),
  ).toHaveProperty("href", expect.stringContaining("/translations/review"));
  expect(screen.getByRole("link", { name: "Przegląd" })).toBeTruthy();
  await expectNoAxeViolations(container);

  fireEvent.click(
    within(home!).getByRole("button", {
      name: "Działania dla: Strona główna · English",
    }),
  );
  const menu = await screen.findByRole("menu");
  expect(
    within(menu)
      .getAllByRole("menuitem")
      .map((entry) => [entry.textContent, entry.getAttribute("href")]),
  ).toEqual([
    ["Otwórz", `/panel/sites/pages/${HOME}?language=en`],
    ["Odrzuć", null],
  ]);
});

test("accepting one asks first, sends the version seen and says what happened", async () => {
  api.decideTranslationReview.mockResolvedValue({
    items: [{ ...item(), state: "accepted", outcomes: [{ state: "live" }] }],
  });
  view();
  const table = await screen.findByRole("table");
  const [home] = within(table).getAllByRole("row").slice(1);

  fireEvent.click(
    within(home!).getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Zaakceptować tłumaczenie i opublikować je?",
  });
  expect(dialog.textContent).toContain("Strona główna · English");
  expect(api.decideTranslationReview).not.toHaveBeenCalled();

  api.listTranslationReview.mockResolvedValue(page([CARD, REFUSED]));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  await waitFor(() =>
    expect(api.decideTranslationReview).toHaveBeenCalledWith(
      "accept",
      [expect.objectContaining({ id: item().id, version: 1 })],
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Tłumaczenie zaakceptowane i opublikowane."),
  ).toBeTruthy();
  // The list is asked for again and the tab's number follows it.
  expect(
    await screen.findByRole("link", { name: "Do akceptacji (2)" }),
  ).toBeTruthy();
  expect(screen.queryByText("Strona główna")).toBeNull();
});

test("accepted but held back by its source: the reason is said", async () => {
  api.decideTranslationReview.mockResolvedValue({
    items: [
      {
        ...item(),
        state: "accepted",
        outcomes: [{ state: "pending", reason: "locale_home_missing" }],
      },
    ],
  });
  view();
  const table = await screen.findByRole("table");
  fireEvent.click(
    within(table).getAllByRole("button", {
      name: "Zaakceptuj i opublikuj",
    })[0]!,
  );
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Zaakceptuj i opublikuj",
    }),
  );
  expect(
    await screen.findByText(
      "Tłumaczenie zaakceptowane. Nie wszystko trafiło jeszcze na stronę: najpierw musi wyjść strona główna w tym języku.",
    ),
  ).toBeTruthy();
});

test("the marked ones are accepted together; what cannot be accepted is never marked", async () => {
  api.decideTranslationReview.mockResolvedValue({
    items: [
      { ...item(), outcomes: [{ state: "live" }] },
      { ...CARD, outcomes: [{ state: "live" }] },
    ],
  });
  view();
  await screen.findByRole("table");
  const bulk = screen.getByRole("button", { name: "Zaakceptuj zaznaczone" });
  expect(bulk).toHaveProperty("disabled", true);

  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Zaznacz wszystkie, które można zaakceptować",
    }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Zaakceptuj zaznaczone (2)" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Zaakceptować 2 zaznaczone tłumaczenia?",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  await waitFor(() =>
    expect(api.decideTranslationReview).toHaveBeenCalledTimes(1),
  );
  expect(
    api.decideTranslationReview.mock.calls[0]![1].map(
      (row: TranslationReviewItem) => row.id,
    ),
  ).toEqual([item().id, CARD.id]);
  expect(
    await screen.findByText("Zaakceptowano i opublikowano 2 tłumaczenia."),
  ).toBeTruthy();
});

test("discarding says that credits do not come back; a decision made meanwhile reloads the list", async () => {
  api.decideTranslationReview.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "translation_review_changed",
      detail: "",
    } as ConstructorParameters<typeof ApiProblemError>[0]),
  );
  view();
  const table = await screen.findByRole("table");
  const [home] = within(table).getAllByRole("row").slice(1);
  fireEvent.click(
    within(home!).getByRole("button", {
      name: "Działania dla: Strona główna · English",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Odrzuć" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Odrzucić to tłumaczenie?",
  });
  expect(dialog.textContent).toContain(
    "Kredyty za dostarczone tłumaczenie nie wracają.",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Odrzuć" }));

  expect((await screen.findByRole("alert")).textContent).toContain(
    "Ta pozycja zmieniła się albo ktoś już o niej zdecydował",
  );
  expect(api.decideTranslationReview).toHaveBeenCalledWith(
    "discard",
    [expect.objectContaining({ id: item().id })],
    expect.any(String),
  );
  await waitFor(() =>
    expect(api.listTranslationReview).toHaveBeenCalledTimes(2),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a failed decision stays in the dialog, to try again with the same key", async () => {
  api.decideTranslationReview
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce({ items: [{ ...item(), outcomes: [] }] });
  view();
  const table = await screen.findByRole("table");
  fireEvent.click(
    within(table).getAllByRole("button", {
      name: "Zaakceptuj i opublikuj",
    })[0]!,
  );
  const dialog = await screen.findByRole("dialog");
  const confirm = within(dialog).getByRole("button", {
    name: "Zaakceptuj i opublikuj",
  });
  fireEvent.click(confirm);
  expect((await within(dialog).findByRole("alert")).textContent).toBe(
    "Nie udało się zapisać decyzji. Spróbuj ponownie.",
  );
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(api.decideTranslationReview).toHaveBeenCalledTimes(2),
  );
  const [first, second] = api.decideTranslationReview.mock.calls;
  expect(second![2]).toBe(first![2]);
});

test("a source taken off the site is its own decision, in its own words", async () => {
  const gone = item({ reason: "source_withdrawn" });
  api.listTranslationReview.mockResolvedValue(page([gone]));
  api.decideTranslationReview.mockResolvedValue({
    items: [{ ...gone, outcomes: [] }],
  });
  view();
  const table = await screen.findByRole("table");
  // Never part of a bulk acceptance.
  expect(within(table).queryByRole("checkbox")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Zaakceptuj zaznaczone" }),
  ).toBeNull();
  fireEvent.click(
    within(table).getByRole("button", { name: "Zdejmij też tłumaczenie" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Zdjąć też tłumaczenie?",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zdejmij też tłumaczenie" }),
  );
  expect(await screen.findByText("Tłumaczenie zdjęte ze strony.")).toBeTruthy();
});

test("the reason filter asks the server and keeps the tab's number", async () => {
  view();
  await screen.findByRole("table");
  api.listTranslationReview.mockResolvedValue(page([CARD], 1));
  fireEvent.change(screen.getByLabelText("Powód"), {
    target: { value: "review_mode" },
  });
  await waitFor(() =>
    expect(api.listTranslationReview).toHaveBeenLastCalledWith({
      limit: 50,
      reason: "review_mode",
    }),
  );
  await waitFor(() => expect(screen.queryByText("Strona główna")).toBeNull());
  expect(screen.getByRole("link", { name: "Do akceptacji (3)" })).toBeTruthy();
});

test("nothing waiting, loading and a failed read", async () => {
  api.listTranslationReview.mockResolvedValueOnce(page([]));
  const empty = view();
  expect(
    await screen.findByText("Nic nie czeka na Twoją decyzję."),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "Do akceptacji" })).toBeTruthy();
  await expectNoAxeViolations(empty.container);
  empty.unmount();

  let fail: (error: unknown) => void = () => undefined;
  api.listTranslationReview.mockReturnValueOnce(
    new Promise((_resolve, reject) => {
      fail = reject;
    }),
  );
  const { container } = view();
  expect(container.querySelector("[aria-busy=true]")).not.toBeNull();
  fail(new Error("network"));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(
    "Nie udało się wczytać tłumaczeń do akceptacji.",
  );
  fireEvent.click(
    within(alert).getByRole("button", { name: "Spróbuj ponownie" }),
  );
  expect(await screen.findByText("Strona główna")).toBeTruthy();
});

test("English words and axe", async () => {
  const { container } = view("en");
  const table = await screen.findByRole("table", {
    name: "Translations waiting for a decision",
  });
  expect(
    within(table).getByText("It would change your corrections"),
  ).toBeTruthy();
  expect(
    within(table).getAllByRole("button", { name: "Accept and publish" }),
  ).toHaveLength(2);
  expect(screen.getByRole("link", { name: "To approve (3)" })).toBeTruthy();
  await expectNoAxeViolations(container);
});
