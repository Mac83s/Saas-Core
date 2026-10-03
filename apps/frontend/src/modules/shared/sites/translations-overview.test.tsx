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

import type { TranslationOverview } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import {
  TranslateSiteAction,
  TranslationsOverview,
} from "./translations-overview";

const { api } = vi.hoisted(() => ({
  api: {
    getSiteTranslationOverview: vi.fn(),
    getTranslationOffer: vi.fn(),
    quoteTranslation: vi.fn(),
    getCustomerCredits: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const SITE = "0199f0a0-0000-7000-8000-000000000001";
const HOME = "0199f0a0-0000-7000-8000-0000000000a1";
const CONTACT = "0199f0a0-0000-7000-8000-0000000000a2";

type Row = TranslationOverview["items"][number];

function page(id: string, title: string, cells: Row["cells"]): Row {
  return { kind: "page", id, title, cells };
}

const cell = (
  locale: string,
  state: Row["cells"][number]["state"],
  extra: Partial<Row["cells"][number]> = {},
): Row["cells"][number] => ({
  locale,
  state,
  untranslated: null,
  metadata_complete: null,
  ...extra,
});

const PAGES: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    page(HOME, "Strona główna", [
      cell("en", "pending", { untranslated: 0, metadata_complete: true }),
      cell("de", "complete", { untranslated: 0, metadata_complete: true }),
    ]),
    page(CONTACT, "Kontakt", [
      cell("en", "untranslated", { untranslated: 3, metadata_complete: false }),
      cell("de", "missing"),
    ]),
  ],
  next_cursor: null,
};

const OFFER = {
  available: true,
  reasons: [],
  billing: {
    mode: "credits",
    operation_key: "translation.text",
    unit_characters: 1000,
    credits_per_unit: 1,
  },
};

function view(locale: "pl" | "en" = "pl", reloadKey = 0) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <TranslationsOverview reloadKey={reloadKey} siteId={SITE} />
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
  api.getSiteTranslationOverview.mockResolvedValue(PAGES);
  api.getTranslationOffer.mockResolvedValue(OFFER);
  api.getCustomerCredits.mockResolvedValue({ balance: { available: 40 } });
});

test("lists every page against the site's other languages, with the way into each version", async () => {
  const { container } = view();

  const table = await screen.findByRole("table", {
    name: "Podstrony i wpisy w pozostałych językach strony",
  });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual(["Podstrona", "English", "Deutsch", "Działania"]);
  const [home, contact] = within(table).getAllByRole("row").slice(1);
  expect(within(home!).getByText("Czeka na akceptację")).toBeTruthy();
  expect(within(home!).getByText("Przetłumaczona")).toBeTruthy();
  expect(within(contact!).getByText("Niepełna")).toBeTruthy();
  expect(within(contact!).getByText("brakuje 3 fragmentów")).toBeTruthy();
  expect(
    within(contact!).getByText("bez własnego adresu, tytułu lub opisu"),
  ).toBeTruthy();
  expect(within(contact!).getByText("Brak")).toBeTruthy();
  expect(api.getSiteTranslationOverview).toHaveBeenCalledWith(SITE, {
    kind: "page",
    limit: 50,
  });
  await expectNoAxeViolations(container);

  // Two languages: each version's editor is under the row's „…”.
  fireEvent.click(
    within(contact!).getByRole("button", { name: "Działania dla: Kontakt" }),
  );
  const menu = await screen.findByRole("menu");
  expect(
    within(menu)
      .getAllByRole("menuitem")
      .map((item) => [item.textContent, item.getAttribute("href")]),
  ).toEqual([
    ["Edytuj: English", `/panel/sites/pages/${CONTACT}?language=en`],
    ["Edytuj: Deutsch", `/panel/sites/pages/${CONTACT}?language=de`],
    ["Przetłumacz (AI)", null],
  ]);
});

test("the row's order quotes only the languages still to translate", async () => {
  api.quoteTranslation.mockResolvedValue({
    digest: "d",
    units: 1,
    credits: 1,
    characters: 320,
    lines: [
      { locale: "en", outcome: "live", proposals: 0, excluded: null },
      { locale: "de", outcome: "live", proposals: 0, excluded: null },
    ],
  });
  view();
  const table = await screen.findByRole("table");
  // The offer arrives on its own: wait for the action it brings.
  await waitFor(() => expect(api.getTranslationOffer).toHaveBeenCalled());
  const [home, contact] = within(table).getAllByRole("row").slice(1);

  // Nothing to translate where one version waits and the other is complete.
  fireEvent.click(
    within(home!).getByRole("button", {
      name: "Działania dla: Strona główna",
    }),
  );
  expect(
    within(await screen.findByRole("menu")).queryByText("Przetłumacz (AI)"),
  ).toBeNull();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

  fireEvent.click(
    within(contact!).getByRole("button", { name: "Działania dla: Kontakt" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: /Przetłumacz/ }));
  expect(
    await screen.findByRole("dialog", { name: "Przetłumaczyć automatycznie?" }),
  ).toBeTruthy();
  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith(
      ["en", "de"].map((locale) => ({
        source_key: "sites.page",
        object_id: CONTACT,
        locale,
        basis: "published",
      })),
      "propose",
    ),
  );
});

test("one other language puts its editor in sight; English words and axe", async () => {
  api.getSiteTranslationOverview.mockResolvedValue({
    locales: ["en"],
    items: [page(CONTACT, "Kontakt", [cell("en", "outdated")])],
    next_cursor: null,
  });
  const { container } = view("en");

  const table = await screen.findByRole("table", {
    name: "Pages and articles in the site's other languages",
  });
  expect(within(table).getByText("Out of date")).toBeTruthy();
  expect(
    within(table).getByRole("link", { name: "Edit: English" }),
  ).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/pages/${CONTACT}?language=en`),
  );
  // One language: nothing to choose in a language filter.
  expect(screen.queryByLabelText("Language")).toBeNull();
  await expectNoAxeViolations(container);
});

test("filters ask the server; articles lead to the blog", async () => {
  view();
  await screen.findByRole("table");

  fireEvent.change(screen.getByLabelText("Język"), { target: { value: "de" } });
  await waitFor(() =>
    expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
      kind: "page",
      limit: 50,
      locale: "de",
    }),
  );
  fireEvent.change(screen.getByLabelText("Stan"), {
    target: { value: "missing" },
  });
  await waitFor(() =>
    expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
      kind: "page",
      limit: 50,
      locale: "de",
      state: "missing",
    }),
  );
  // The language list stays the site's, not the narrowed answer's.
  expect(
    within(screen.getByLabelText("Język"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Wszystkie języki", "English", "Deutsch"]);

  api.getSiteTranslationOverview.mockResolvedValue({
    locales: ["de"],
    items: [
      {
        kind: "entry",
        id: "0199f0a0-0000-7000-8000-0000000000e1",
        title: "Jak dbać o włosy zimą",
        cells: [cell("de", "draft")],
      },
    ],
    next_cursor: null,
  });
  fireEvent.change(screen.getByLabelText("Rodzaj"), {
    target: { value: "entry" },
  });
  // Pages never stand under the articles' column while those are on the way.
  expect(screen.queryByText("Kontakt")).toBeNull();
  // The states are the kind's own: the page's state filter is dropped.
  await waitFor(() =>
    expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
      kind: "entry",
      limit: 50,
      locale: "de",
    }),
  );
  expect(
    await within(await screen.findByRole("table")).findByText("Szkic"),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "Otwórz blog" })).toHaveProperty(
    "href",
    expect.stringContaining(`/panel/sites/blog?site=${SITE}`),
  );
  expect(
    screen.getByText(
      "Wpis tłumaczysz w jego karcie „Wersje językowe” w blogu.",
    ),
  ).toBeTruthy();
  expect(
    within(screen.getByLabelText("Stan"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Wszystkie stany", "Brak", "Szkic", "Na stronie"]);
});

test("loading, then a failed read with a way to ask again", async () => {
  let fail: (error: unknown) => void = () => undefined;
  api.getSiteTranslationOverview.mockReturnValueOnce(
    new Promise((_resolve, reject) => {
      fail = reject;
    }),
  );
  const { container } = view();
  expect(container.querySelector("[aria-busy=true]")).not.toBeNull();

  fail(new Error("network"));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(polishMessages.Sites.problem);
  await expectNoAxeViolations(container);

  fireEvent.click(
    within(alert).getByRole("button", { name: "Spróbuj ponownie" }),
  );
  expect(await screen.findByText("Kontakt")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a site with one language says so and leads to the languages", async () => {
  api.getSiteTranslationOverview.mockResolvedValue({
    locales: [],
    items: [page(HOME, "Strona główna", [])],
    next_cursor: null,
  });
  const { container } = view();

  expect(
    await screen.findByText("Ta strona ma na razie jeden język."),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", {
      name: "Dodaj język w Ustawienia › Języki i tłumaczenia",
    }),
  ).toHaveProperty(
    "href",
    expect.stringContaining("/panel/settings/languages"),
  );
  expect(screen.queryByRole("table")).toBeNull();
  await expectNoAxeViolations(container);
});

test("no pages yet and nothing narrowing the list: its own empty words", async () => {
  api.getSiteTranslationOverview.mockResolvedValue({
    locales: ["en"],
    items: [],
    next_cursor: null,
  });
  view();
  expect(
    await screen.findByText("Ta strona nie ma jeszcze podstron."),
  ).toBeTruthy();
});

test("the next server page is appended on request", async () => {
  api.getSiteTranslationOverview
    .mockResolvedValueOnce({ ...PAGES, next_cursor: CONTACT })
    .mockResolvedValueOnce({
      locales: ["en", "de"],
      items: [
        page("0199f0a0-0000-7000-8000-0000000000a3", "Oferta", [
          cell("en", "complete"),
          cell("de", "complete"),
        ]),
      ],
      next_cursor: null,
    });
  view();
  fireEvent.click(
    await screen.findByRole("button", { name: "Wczytaj więcej" }),
  );
  expect(await screen.findByText("Oferta")).toBeTruthy();
  expect(screen.getByText("Kontakt")).toBeTruthy();
  expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
    kind: "page",
    limit: 50,
    cursor: CONTACT,
  });
  expect(screen.queryByRole("button", { name: "Wczytaj więcej" })).toBeNull();
});

test("an engine that cannot take orders says why and the list still works", async () => {
  api.getTranslationOffer.mockResolvedValue({
    ...OFFER,
    available: false,
    reasons: ["worker_unavailable"],
  });
  view();
  expect(
    await screen.findByText(
      "Automatyczne tłumaczenie nie jest teraz dostępne: usługa tłumaczeń chwilowo nie odpowiada. Możesz przetłumaczyć ręcznie.",
    ),
  ).toBeTruthy();
  const table = await screen.findByRole("table");
  fireEvent.click(
    within(table).getByRole("button", { name: "Działania dla: Kontakt" }),
  );
  const menu = await screen.findByRole("menu");
  expect(within(menu).queryByText("Przetłumacz (AI)")).toBeNull();
  expect(within(menu).getByText("Edytuj: English")).toBeTruthy();
});

function action(onDone = vi.fn()) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <TranslateSiteAction onDone={onDone} siteId={SITE} />
    </NextIntlClientProvider>,
  );
}

test("the page's action gathers every page's missing languages across the server's pages", async () => {
  api.getSiteTranslationOverview
    .mockResolvedValueOnce({ ...PAGES, next_cursor: CONTACT })
    .mockResolvedValueOnce({
      locales: ["en", "de"],
      items: [
        page("0199f0a0-0000-7000-8000-0000000000a3", "Oferta", [
          cell("en", "outdated"),
          cell("de", "complete"),
        ]),
      ],
      next_cursor: null,
    });
  api.quoteTranslation.mockResolvedValue({
    digest: "d",
    units: 1,
    credits: 1,
    characters: 900,
    lines: [],
  });
  action();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Przetłumacz brakujące i nieaktualne (AI)",
    }),
  );
  await screen.findByRole("dialog", { name: "Przetłumaczyć automatycznie?" });
  await waitFor(() => expect(api.quoteTranslation).toHaveBeenCalled());
  expect(
    api.quoteTranslation.mock.calls[0]![0].map(
      (target: { object_id: string; locale: string }) =>
        `${target.object_id}:${target.locale}`,
    ),
  ).toEqual([
    `${CONTACT}:en`,
    `${CONTACT}:de`,
    "0199f0a0-0000-7000-8000-0000000000a3:en",
  ]);
  expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
    kind: "page",
    limit: 100,
    cursor: CONTACT,
  });
});

test("the page's action says when nothing is left, and is absent without an engine", async () => {
  api.getSiteTranslationOverview.mockResolvedValue({
    locales: ["en"],
    items: [page(HOME, "Strona główna", [cell("en", "complete")])],
    next_cursor: null,
  });
  const first = action();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Przetłumacz brakujące i nieaktualne (AI)",
    }),
  );
  expect(
    await screen.findByText("Wszystkie podstrony są przetłumaczone."),
  ).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  first.unmount();

  api.getTranslationOffer.mockRejectedValue(new Error("no engine"));
  const second = action();
  await waitFor(() => expect(api.getTranslationOffer).toHaveBeenCalledTimes(2));
  expect(second.container.querySelector("button")).toBeNull();
});
