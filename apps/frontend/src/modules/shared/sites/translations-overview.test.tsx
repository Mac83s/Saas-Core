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
  type TranslationOverview,
} from "@saas-core/api-client";
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
    listTranslationJobs: vi.fn(),
    decideTranslationReview: vi.fn(),
    getTranslationReview: vi.fn(),
    getSiteTexts: vi.fn(),
    saveSiteTexts: vi.fn(),
    publishSiteTexts: vi.fn(),
  },
}));
// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const SITE = "0199f0a0-0000-7000-8000-000000000001";
const HOME = "0199f0a0-0000-7000-8000-0000000000a1";
const CONTACT = "0199f0a0-0000-7000-8000-0000000000a2";
const CARD = "0199f0a0-0000-7000-8000-0000000000c1";
const REVIEW = "0199f0a0-0000-7000-8000-0000000000f1";

type Row = TranslationOverview["items"][number];

function page(id: string, title: string, cells: Row["cells"]): Row {
  return {
    kind: "page",
    id,
    source_key: "sites.page",
    source_id: id,
    title,
    cells,
  };
}

function other(
  source_key: string,
  id: string,
  title: string,
  cells: Row["cells"],
): Row {
  return { kind: "other", id, source_key, source_id: id, title, cells };
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
  on_site: null,
  path: null,
  review_id: null,
  review_version: null,
  review_comparable: null,
  ...extra,
});

const PAGES: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    page(HOME, "Strona główna", [
      cell("en", "pending", {
        untranslated: 0,
        metadata_complete: true,
        on_site: true,
      }),
      cell("de", "complete", {
        untranslated: 0,
        metadata_complete: true,
        on_site: false,
      }),
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

const onDecided = vi.fn();

function view(locale: "pl" | "en" = "pl", reloadKey = 0) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <TranslationsOverview
        onDecided={onDecided}
        publicBaseUrl="https://studio.example.test"
        reloadKey={reloadKey}
        siteId={SITE}
      />
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
  api.listTranslationJobs.mockResolvedValue({ items: [], next_cursor: null });
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
  // Translated is not yet published: the cell says where the version stands.
  expect(within(home!).getByText("na stronie")).toBeTruthy();
  expect(within(home!).getByText("jeszcze nie na stronie")).toBeTruthy();
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

  // Two languages: each version's editor is in its own column, in sight…
  expect(
    within(contact!)
      .getAllByRole("link", { name: /^Edytuj: / })
      .map((link) => [
        link.getAttribute("aria-label"),
        link.textContent,
        link.getAttribute("href"),
      ]),
  ).toEqual([
    ["Edytuj: English", "Edytuj", `/panel/sites/pages/${CONTACT}?language=en`],
    ["Edytuj: Deutsch", "Edytuj", `/panel/sites/pages/${CONTACT}?language=de`],
  ]);
  // …and under the row's „…”, beside the order.
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
        source_key: "sites.entry",
        source_id: "0199f0a0-0000-7000-8000-0000000000e2",
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
      "Ręcznie wpis tłumaczysz w jego karcie „Wersje językowe” w blogu.",
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

test("the page's action gathers every missing language — pages, articles, the site's texts, the card — across the server's pages", async () => {
  const ENTRY = "0199f0a0-0000-7000-8000-0000000000e2";
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
    })
    // Then the articles: only a missing version is ordered, by the entry
    // in the site's own language.
    .mockResolvedValueOnce({
      locales: ["en", "de"],
      items: [
        {
          kind: "entry",
          id: "0199f0a0-0000-7000-8000-0000000000e1",
          source_key: "sites.entry",
          source_id: ENTRY,
          title: "Jak dbać o włosy zimą",
          cells: [cell("en", "draft"), cell("de", "missing")],
        },
      ],
      next_cursor: null,
    })
    // Then everything else: the site's own texts, the card, the services.
    .mockResolvedValueOnce({
      locales: ["en", "de"],
      items: [
        other("sites.site_texts", SITE, "Studio", [
          cell("en", "complete"),
          cell("de", "untranslated", { untranslated: 1 }),
        ]),
        other("profiles.public_profile", CARD, "Studio", [
          cell("en", "pending"),
          cell("de", "missing"),
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
    `${ENTRY}:de`,
    `${SITE}:de`,
    `${CARD}:de`,
  ]);
  expect(
    api.quoteTranslation.mock.calls[0]![0].map(
      (target: { source_key: string }) => target.source_key,
    ),
  ).toEqual([
    "sites.page",
    "sites.page",
    "sites.page",
    "sites.entry",
    "sites.site_texts",
    "profiles.public_profile",
  ]);
  expect(api.getSiteTranslationOverview.mock.calls.slice(-3)).toEqual([
    [SITE, { kind: "page", limit: 100, cursor: CONTACT }],
    [SITE, { kind: "entry", limit: 100 }],
    [SITE, { kind: "other", limit: 100 }],
  ]);
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
    await screen.findByText("Wszystko jest już przetłumaczone."),
  ).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  first.unmount();

  api.getTranslationOffer.mockRejectedValue(new Error("no engine"));
  const second = action();
  await waitFor(() => expect(api.getTranslationOffer).toHaveBeenCalledTimes(2));
  expect(second.container.querySelector("button")).toBeNull();
});

test("a job that runs stands above the list with its progress", async () => {
  api.listTranslationJobs.mockResolvedValue({
    items: [
      {
        id: "0199f0a0-0000-7000-8000-0000000000d1",
        state: "running",
        trigger: "click",
        error_code: "",
        confirmation_required: false,
        created_at: "2026-10-03T12:00:00Z",
        next_attempt_at: "2026-10-03T12:00:00Z",
        items: [{ state: "written" }, { state: "queued" }, { state: "queued" }],
      },
    ],
    next_cursor: null,
  });
  const { container } = view();

  const bar = await screen.findByRole("region", { name: "Tłumaczenia w toku" });
  expect(bar.textContent).toContain("Tłumaczenie w toku: 1 z 3");
  expect(bar.textContent).toContain("zlecone 3 paź 2026, 14:00");
  expect(within(bar).getByRole("progressbar")).toBeTruthy();
  expect(api.listTranslationJobs).toHaveBeenCalledWith({
    active: true,
    limit: 5,
  });
  await screen.findByRole("table");
  await expectNoAxeViolations(container);
});

test("no bar where the deployment has no translation engine", async () => {
  api.getTranslationOffer.mockRejectedValue(new Error("404"));
  view();
  await screen.findByRole("table");
  await waitFor(() =>
    expect(api.getSiteTranslationOverview).toHaveBeenCalled(),
  );
  expect(api.listTranslationJobs).not.toHaveBeenCalled();
  expect(screen.queryByRole("region")).toBeNull();
});

test("an article's missing version is ordered by its entry in the site's own language", async () => {
  const GROUP = "0199f0a0-0000-7000-8000-0000000000e1";
  const ENTRY = "0199f0a0-0000-7000-8000-0000000000e2";
  api.getSiteTranslationOverview.mockResolvedValue({
    locales: ["en", "de"],
    items: [
      {
        kind: "entry",
        id: GROUP,
        source_key: "sites.entry",
        source_id: ENTRY,
        title: "Jak dbać o włosy zimą",
        cells: [cell("en", "draft"), cell("de", "missing")],
      },
      {
        // No entry in the site's own language: nothing an order could name.
        kind: "entry",
        id: "0199f0a0-0000-7000-8000-0000000000e3",
        source_key: "sites.entry",
        source_id: null,
        title: "Winter hair care",
        // A published article says where visitors read it.
        cells: [
          cell("en", "published", { path: "/en/blog/winter-hair-care/" }),
          cell("de", "missing"),
        ],
      },
    ],
    next_cursor: null,
  });
  api.quoteTranslation.mockResolvedValue({
    digest: "d",
    units: 1,
    credits: 1,
    characters: 900,
    lines: [{ locale: "de", outcome: "draft", proposals: 0, excluded: null }],
  });
  view();
  const table = await screen.findByRole("table");
  await waitFor(() => expect(api.getTranslationOffer).toHaveBeenCalled());
  const [ordered, orphan] = within(table).getAllByRole("row").slice(1);
  // An article is published or a draft, never „na stronie” twice.
  expect(within(ordered!).queryByText("jeszcze nie na stronie")).toBeNull();

  expect(
    within(orphan!).queryByRole("button", { name: /^Działania dla:/ }),
  ).toBeNull();
  expect(
    within(orphan!)
      .getByRole("link", {
        name: "Otwórz na stronie: Winter hair care — English",
      })
      .getAttribute("href"),
  ).toBe("https://studio.example.test/en/blog/winter-hair-care/");
  fireEvent.click(
    within(ordered!).getByRole("button", {
      name: "Działania dla: Jak dbać o włosy zimą",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: /Przetłumacz/ }));
  // Only the missing language, and the entry — not the group — is named.
  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith(
      [
        {
          source_key: "sites.entry",
          object_id: ENTRY,
          locale: "de",
          basis: "published",
        },
      ],
      "propose",
    ),
  );
});

const WAITING_PAGE: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    page(HOME, "Strona główna", [
      cell("en", "pending", {
        untranslated: 0,
        metadata_complete: true,
        on_site: true,
        path: "/en/home/",
        review_id: REVIEW,
        review_version: 3,
        review_comparable: false,
      }),
      cell("de", "missing"),
    ]),
  ],
  next_cursor: null,
};

test("a cell leads to the version's preview and its place on the site, and takes the decision on what waits", async () => {
  api.getSiteTranslationOverview.mockResolvedValue(WAITING_PAGE);
  api.decideTranslationReview.mockResolvedValue({
    items: [{ id: REVIEW, outcomes: [{ state: "live", reason: null }] }],
  });
  const { container } = view();
  const table = await screen.findByRole("table");
  const [home] = within(table).getAllByRole("row").slice(1);

  expect(
    within(home!)
      .getByRole("link", { name: "Podgląd: Strona główna — English" })
      .getAttribute("href"),
  ).toBe(`/panel/sites/pages/${HOME}?language=en&preview=1`);
  const onSite = within(home!).getByRole("link", {
    name: "Otwórz na stronie: Strona główna — English",
  });
  expect(onSite.getAttribute("href")).toBe(
    "https://studio.example.test/en/home/",
  );
  expect(onSite.getAttribute("target")).toBe("_blank");
  // A language with no version has nothing to preview, open or accept.
  expect(
    within(home!).queryByRole("link", {
      name: /^(Podgląd|Otwórz na stronie): .*Deutsch$/,
    }),
  ).toBeNull();
  expect(
    within(home!).queryByRole("button", { name: /^Zaakceptuj: .*Deutsch$/ }),
  ).toBeNull();
  await expectNoAxeViolations(container);

  fireEvent.click(
    within(home!).getByRole("button", {
      name: "Zaakceptuj: Strona główna — English",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Zaakceptować tłumaczenie i opublikować je?",
  });
  expect(dialog.textContent).toContain("Strona główna · English");
  expect(api.decideTranslationReview).not.toHaveBeenCalled();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  await waitFor(() =>
    expect(api.decideTranslationReview).toHaveBeenCalledWith(
      "accept",
      [{ id: REVIEW, version: 3 }],
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Tłumaczenie zaakceptowane i opublikowane."),
  ).toBeTruthy();
  // The list is asked again and the tab's number with it.
  await waitFor(() =>
    expect(api.getSiteTranslationOverview).toHaveBeenCalledTimes(2),
  );
  expect(onDecided).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a result decided meanwhile says so and the list is read again; a refusal stays in the dialog", async () => {
  api.getSiteTranslationOverview.mockResolvedValue(WAITING_PAGE);
  const problem = (status: number, code: string) =>
    new ApiProblemError({
      type: "about:blank",
      title: "",
      status,
      code,
      detail: "",
    } as ConstructorParameters<typeof ApiProblemError>[0]);
  api.decideTranslationReview
    .mockRejectedValueOnce(problem(403, "person_required"))
    .mockRejectedValueOnce(problem(409, "translation_review_changed"));
  view();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Zaakceptuj: Strona główna — English",
    }),
  );
  const dialog = await screen.findByRole("dialog");
  const confirm = within(dialog).getByRole("button", {
    name: "Zaakceptuj i opublikuj",
  });
  fireEvent.click(confirm);
  expect((await within(dialog).findByRole("alert")).textContent).toBe(
    "Tę decyzję podejmuje osoba z prawem publikacji.",
  );

  fireEvent.click(confirm);
  expect(
    await screen.findByText(
      "Ta pozycja zmieniła się albo ktoś już o niej zdecydował — poniżej aktualna lista.",
    ),
  ).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(api.getSiteTranslationOverview).toHaveBeenCalledTimes(2);
});

const CATALOG = "0199f0a0-0000-7000-8000-0000000000c2";
const OTHER: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    other("sites.site_texts", SITE, "Studio Testowe", [
      cell("en", "untranslated", { untranslated: 1 }),
      cell("de", "missing", { untranslated: 2 }),
    ]),
    other("profiles.public_profile", CARD, "Studio Testowe", [
      cell("en", "complete", { untranslated: 0 }),
      cell("de", "pending", {
        untranslated: 2,
        review_id: REVIEW,
        review_version: 5,
        review_comparable: true,
      }),
    ]),
    other("booking.catalog", CATALOG, "Studio Testowe", [
      cell("en", "outdated", { untranslated: 0 }),
    ]),
  ],
  next_cursor: null,
};

async function otherRows() {
  api.getSiteTranslationOverview.mockImplementation(
    async (_site: string, query: { kind?: string }) =>
      query.kind === "other" ? OTHER : PAGES,
  );
  const rendered = view();
  await screen.findByText("Kontakt");
  fireEvent.change(screen.getByLabelText("Rodzaj"), {
    target: { value: "other" },
  });
  await screen.findByText("Nagłówek i stopka strony");
  const table = screen.getByRole("table");
  return { ...rendered, rows: within(table).getAllByRole("row").slice(1) };
}

test("the site's own texts, the card and the services are rows of the same list", async () => {
  const { container, rows } = await otherRows();
  expect(
    within(screen.getByLabelText("Rodzaj"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual([
    "Podstrony",
    "Wpisy bloga",
    "Nagłówek i stopka, wizytówka, usługi",
  ]);
  expect(api.getSiteTranslationOverview).toHaveBeenLastCalledWith(SITE, {
    kind: "other",
    limit: 50,
  });
  expect(screen.getAllByRole("columnheader")[0]!.textContent).toBe("Treść");
  const [texts, card, catalog] = rows;
  // Three things carry the company's name: each row says which it is.
  expect(
    rows.map((row) => within(row).getAllByText(/./)[1]!.textContent),
  ).toEqual(["Nagłówek i stopka strony", "Wizytówka", "Usługi i rezerwacje"]);
  expect(within(texts!).getByText("brakuje 1 fragmentu")).toBeTruthy();
  expect(within(catalog!).getByText("Nieaktualna")).toBeTruthy();
  // A card and the services are translated where they are edited.
  expect(
    within(card!).getByRole("link", { name: "Edytuj" }).getAttribute("href"),
  ).toBe("/panel/profile");
  expect(
    within(catalog!).getByRole("link", { name: "Edytuj" }).getAttribute("href"),
  ).toBe("/panel/settings/services");
  // No page behind these rows: nothing to preview or to open on the site.
  expect(screen.queryByRole("link", { name: /^Podgląd/ })).toBeNull();
  expect(
    screen.getByText(/Wizytówkę i nazwy usług — tam, gdzie się je edytuje/),
  ).toBeTruthy();
  await expectNoAxeViolations(container);

  // The order names each object by its own source.
  api.quoteTranslation.mockResolvedValue({
    digest: "d",
    units: 1,
    credits: 1,
    characters: 40,
    lines: [],
  });
  fireEvent.click(
    within(texts!).getByRole("button", {
      name: "Działania dla: Studio Testowe",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: /Przetłumacz/ }));
  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith(
      ["en", "de"].map((locale) => ({
        source_key: "sites.site_texts",
        object_id: SITE,
        locale,
        basis: "published",
      })),
      "propose",
    ),
  );
});

test("the site's texts open in their sheet, one language at a time", async () => {
  api.getSiteTexts.mockResolvedValue({
    site_id: SITE,
    locale: "de",
    version: "v1",
    items: [
      {
        key: "footer/text",
        role: "footer",
        source_text: "Zapraszamy",
        text: "",
        origin: "",
        state: "missing",
        pending_text: "",
        pending_reason: "",
      },
    ],
  });
  const { rows } = await otherRows();
  fireEvent.click(
    within(rows[0]!).getByRole("button", { name: "Edytuj: Deutsch" }),
  );
  const sheet = await screen.findByRole("dialog", {
    name: "Nagłówek i stopka — Deutsch",
  });
  expect(api.getSiteTexts).toHaveBeenCalledWith(SITE, "de");
  expect(await within(sheet).findByLabelText("Tekst stopki")).toBeTruthy();
});

test("a card's waiting text is read beside its source before it is accepted", async () => {
  api.getTranslationReview.mockResolvedValue({
    id: REVIEW,
    version: 6,
    locale: "de",
    source_locale: "pl",
    acceptable: true,
    comparable: true,
    fits: true,
    units: [
      {
        key: "headline",
        source_text: "Salon fryzjerski w centrum",
        current_text: "",
        proposed_text: "Friseursalon im Zentrum",
      },
    ],
  });
  api.decideTranslationReview.mockResolvedValue({
    items: [{ id: REVIEW, outcomes: [{ state: "live", reason: null }] }],
  });
  const { rows } = await otherRows();
  fireEvent.click(
    within(rows[1]!).getByRole("button", {
      name: "Zaakceptuj: Studio Testowe — Deutsch",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Studio Testowe · Deutsch",
  });
  expect(api.getTranslationReview).toHaveBeenCalledWith(REVIEW);
  expect(
    await within(dialog).findByText("Friseursalon im Zentrum"),
  ).toBeTruthy();
  // Discarding is the queue's own question: not offered from the overview.
  expect(within(dialog).queryByRole("button", { name: "Odrzuć" })).toBeNull();
  expect(api.decideTranslationReview).not.toHaveBeenCalled();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  // At the version the dialog read, not the one the list had.
  await waitFor(() =>
    expect(api.decideTranslationReview).toHaveBeenCalledWith(
      "accept",
      [{ id: REVIEW, version: 6 }],
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Tłumaczenie zaakceptowane i opublikowane."),
  ).toBeTruthy();
});
