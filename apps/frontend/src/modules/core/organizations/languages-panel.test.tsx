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

import type { PublicLocales } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { LanguagesPanel } from "./languages-panel";

const { api } = vi.hoisted(() => ({
  api: {
    getPublicLocales: vi.fn(),
    previewPublicLocales: vi.fn(),
    changePublicLocales: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const offered = [
  { code: "pl", native_name: "Polski", english_name: "Polish" },
  { code: "en", native_name: "English", english_name: "English" },
  { code: "de", native_name: "Deutsch", english_name: "German" },
];

function state(overrides: Partial<PublicLocales> = {}): PublicLocales {
  return {
    public_locales: ["pl", "en"],
    version: 4,
    offered,
    limit: { allowed: true, additional_max: 1, reason: "" },
    protected: { pl: "site_default_not_removable" },
    ...overrides,
  } as PublicLocales;
}

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <LanguagesPanel />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getPublicLocales.mockResolvedValue(state());
  api.changePublicLocales.mockResolvedValue({});
});

test("lists the company's languages in order, with the customers' language and the protected one", async () => {
  const { container } = view();

  const table = await screen.findByRole("table", { name: "Języki firmy w kolejności" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
    "Polskipl",
    "Englishen",
  ]);
  expect(within(rows[0]!).getByText("Język klientów")).toBeTruthy();
  expect(within(rows[0]!).getByText("Język źródłowy strony")).toBeTruthy();
  expect(screen.getByText("Plan pozwala na 1 język poza pierwszym.")).toBeTruthy();
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("adds a language the product offers and sends the version it read", async () => {
  view();

  fireEvent.click(await screen.findByRole("button", { name: "Dodaj język" }));
  const dialog = await screen.findByRole("dialog", { name: "Dodaj język" });
  expect(
    within(dialog)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Deutsch"]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj język" }));

  await waitFor(() => expect(api.changePublicLocales).toHaveBeenCalledOnce());
  expect(api.changePublicLocales.mock.calls[0]?.[0]).toEqual({
    public_locales: ["pl", "en", "de"],
    expected_version: 4,
  });
  expect(await screen.findByText("Dodano język Deutsch.")).toBeTruthy();
});

test("shows which addresses a removal redirects before it removes the language", async () => {
  api.previewPublicLocales.mockResolvedValue({
    before: ["pl", "en"],
    public_locales: ["pl"],
    added: [],
    removed: ["en"],
    version: 5,
    limit: { allowed: true, additional_max: 1, reason: "" },
    person_gates: ["Usunięcie języka firmy"],
    redirects: [
      { locale: "en", path: "/en/", target: "/" },
      { locale: "en", path: "/en/contact/", target: "/kontakt/" },
    ],
  });
  view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Działania dla języka English" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń język" }));
  const dialog = await screen.findByRole("dialog", { name: "Usunąć język English?" });
  const list = within(dialog).getByRole("list", {
    name: "Adresy, które zaczną przekierowywać",
  });
  expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "/en/ → /",
    "/en/contact/ → /kontakt/",
  ]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń język" }));

  await waitFor(() =>
    expect(api.changePublicLocales.mock.calls[0]?.[0]).toEqual({
      public_locales: ["pl"],
      expected_version: 4,
    }),
  );
});

test("speaks English too, and a site's source language has nothing to remove", async () => {
  view("en");

  expect(await screen.findByRole("table", { name: "The company's languages in order" })).toBeTruthy();
  fireEvent.click(
    await screen.findByRole("button", { name: "Actions for English" }),
  );
  expect(await screen.findByRole("menuitem", { name: "Remove the language" })).toBeTruthy();
  // Polish is the first language and a site's source: no action is offered.
  expect(screen.queryByRole("button", { name: "Actions for Polski" })).toBeNull();
});
