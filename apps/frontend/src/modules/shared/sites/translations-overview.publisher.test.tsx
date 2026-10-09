import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { TranslationOverview } from "@saas-core/api-client";
import polishMessages from "../../../../messages/pl.json";
import { PanelAccessProvider } from "#components/panel/panel-access";
import type { PanelAccess } from "#lib/panel-navigation";
import {
  TranslateSiteAction,
  TranslationsOverview,
} from "./translations-overview";

/**
 * „Tłumaczenia” in the platform's own workspace (ADR-079 pkt 29): what it
 * writes — entries, and the names of its types, categories and tags. Its
 * builder pages are served at no host, so the list neither shows nor orders
 * them and nothing here leads to the page editor, which its panel has not.
 * A company's list is tested in `translations-overview.test.tsx`, unchanged.
 */
const { api } = vi.hoisted(() => ({
  api: {
    getSiteTranslationOverview: vi.fn(),
    getTranslationOffer: vi.fn(),
    quoteTranslation: vi.fn(),
    getCustomerCredits: vi.fn(),
    listTranslationJobs: vi.fn(),
    listTranslationDemand: vi.fn(),
  },
}));
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const SITE = "0199f0a0-0000-7000-8000-000000000001";
const ENTRY = "0199f0a0-0000-7000-8000-0000000000e1";
const SOURCE = "0199f0a0-0000-7000-8000-0000000000e2";

type Row = TranslationOverview["items"][number];
const cell = (
  locale: string,
  state: Row["cells"][number]["state"],
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
});

const ENTRIES: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    {
      kind: "entry",
      id: ENTRY,
      source_key: "sites.entry",
      source_id: SOURCE,
      title: "Jak wybrać szczeniaka",
      cells: [cell("en", "published"), cell("de", "missing")],
    },
  ],
  next_cursor: null,
};
const NAMES: TranslationOverview = {
  locales: ["en", "de"],
  items: [
    {
      kind: "other",
      id: SITE,
      source_key: "sites.site_texts",
      source_id: SITE,
      title: "Treści platformy",
      cells: [cell("en", "complete"), cell("de", "untranslated")],
    },
  ],
  next_cursor: null,
};

const PUBLISHER: PanelAccess = {
  modules: ["shared.sites", "shared.translation"],
  permissions: null,
  isOwner: true,
  limited: false,
  organizationType: "business",
  publisher: true,
};

function asPublisher(children: ReactNode) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <PanelAccessProvider access={PUBLISHER}>{children}</PanelAccessProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getSiteTranslationOverview.mockImplementation(
    async (_site: string, query: { kind: string }) =>
      query.kind === "entry" ? ENTRIES : NAMES,
  );
  api.getTranslationOffer.mockResolvedValue({
    available: true,
    reasons: [],
    billing: {
      mode: "credits",
      operation_key: "translation.text",
      unit_characters: 1000,
      credits_per_unit: 1,
    },
  });
  api.getCustomerCredits.mockResolvedValue({ balance: { available: 40 } });
  api.listTranslationJobs.mockResolvedValue({ items: [], next_cursor: null });
  api.listTranslationDemand.mockResolvedValue({
    items: [],
    count: 0,
    next_cursor: null,
  });
});

test("wydawca: lista otwiera się na wpisach, a podstron kreatora nie ma wśród rodzajów", async () => {
  const { container } = asPublisher(<TranslationsOverview siteId={SITE} />);

  const table = await screen.findByRole("table", {
    name: "Wpisy w pozostałych językach",
  });
  expect(await within(table).findByText("Jak wybrać szczeniaka")).toBeTruthy();
  // Entries first — never the builder's pages, not even as the first ask.
  expect(
    api.getSiteTranslationOverview.mock.calls.map(([, query]) => query.kind),
  ).toEqual(["entry"]);
  expect(
    [
      ...screen
        .getByLabelText("Rodzaj")
        .querySelectorAll<HTMLOptionElement>("option"),
    ].map((option) => [option.value, option.textContent]),
  ).toEqual([
    ["entry", "Wpisy bloga"],
    ["other", "Nazwy typów treści, kategorii i tagów"],
  ]);
  // Nothing on the screen leads to a page's editor.
  expect(
    [...container.querySelectorAll("a")]
      .map((link) => link.getAttribute("href") ?? "")
      .filter((href) => href.startsWith("/panel/sites/pages")),
  ).toEqual([]);
});

test("wydawca: nazwy typów, kategorii i tagów mają własny rodzaj i własne słowa", async () => {
  asPublisher(<TranslationsOverview siteId={SITE} />);
  await screen.findByText("Jak wybrać szczeniaka");

  fireEvent.change(screen.getByLabelText("Rodzaj"), {
    target: { value: "other" },
  });
  const row = (await screen.findByText("Treści platformy")).closest("tr")!;
  // Not „Nagłówek i stopka strony”: the workspace has no builder site.
  expect(
    within(row).getByText("Nazwy typów treści, kategorii i tagów"),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "Nazwy typów treści, kategorii i tagów tłumaczysz tutaj („Edytuj”).",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/Nagłówek i stopk/)).toBeNull();
});

test("wydawca: „Przetłumacz brakujące” nie pyta o podstrony i ich nie zamawia", async () => {
  api.quoteTranslation.mockResolvedValue({
    digest: "d",
    units: 1,
    credits: 1,
    characters: 900,
    lines: [],
  });
  asPublisher(<TranslateSiteAction onDone={() => undefined} siteId={SITE} />);

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Przetłumacz brakujące i nieaktualne (AI)",
    }),
  );
  await waitFor(() => expect(api.quoteTranslation).toHaveBeenCalled());
  expect(
    api.getSiteTranslationOverview.mock.calls.map(([, query]) => query.kind),
  ).toEqual(["entry", "other"]);
  expect(
    api.quoteTranslation.mock.calls[0]![0].map(
      (target: { source_key: string; object_id: string; locale: string }) =>
        `${target.source_key}:${target.object_id}:${target.locale}`,
    ),
  ).toEqual([`sites.entry:${SOURCE}:de`, `sites.site_texts:${SITE}:de`]);
});
