import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type {
  CustomerDocumentList,
  PublicLocales,
} from "@saas-core/api-client";
import polishMessages from "../../../../messages/pl.json";
import { LanguagesPanel } from "../../core/organizations";
import { TermsLanguagesNotice } from "./terms-languages";

const { api } = vi.hoisted(() => ({
  api: {
    getPublicLocales: vi.fn(),
    changePublicLocales: vi.fn(),
    listCustomerDocuments: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

function languages(codes: string[]): PublicLocales {
  return {
    public_locales: codes,
    version: codes.length,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "en", native_name: "English", english_name: "English" },
      { code: "de", native_name: "Deutsch", english_name: "German" },
    ],
    limit: { allowed: true, additional_max: 2, reason: "" },
    protected: {},
  } as PublicLocales;
}

/** The booking terms in force, written in `written`, for a company that
 *  speaks `codes`. */
function documents(codes: string[], written: string[] | null) {
  return {
    documents: [
      {
        kind: "booking_terms",
        version: 1,
        draft: null,
        in_force: written && { number: 1, locales: written },
        upcoming: null,
        public_url: null,
      },
    ],
    options: { locales: codes },
  } as unknown as CustomerDocumentList;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.changePublicLocales.mockResolvedValue({});
});

function view() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <LanguagesPanel>
        <TermsLanguagesNotice />
      </LanguagesPanel>
    </NextIntlClientProvider>,
  );
}

test("the languages screen warns about a language the booking terms have no text in, again after one is added", async () => {
  api.getPublicLocales.mockResolvedValue(languages(["pl", "en"]));
  api.listCustomerDocuments.mockResolvedValue(documents(["pl", "en"], ["pl"]));
  view();

  const warning = await screen.findByTestId("terms-languages-off");
  expect(warning.textContent).toContain(
    "Regulamin rezerwacji nie ma wersji w języku English — rezerwacja online w tym języku jest wyłączona.",
  );
  expect(
    within(warning).getByRole("link", { name: "Dodaj tekst regulaminu" }),
  ).toHaveAttribute("href", "/panel/settings/documents/booking_terms");

  // German is added: the warning names it too, without a reload.
  api.getPublicLocales.mockResolvedValue(languages(["pl", "en", "de"]));
  api.listCustomerDocuments.mockResolvedValue(
    documents(["pl", "en", "de"], ["pl"]),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj język" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj język" }));
  await waitFor(() =>
    expect(screen.getByTestId("terms-languages-off").textContent).toContain(
      "nie ma wersji w językach: English, Deutsch — rezerwacja online w tych językach jest wyłączona.",
    ),
  );
});

test("no terms in force, or terms in every language, is no warning", async () => {
  api.getPublicLocales.mockResolvedValue(languages(["pl", "en"]));
  api.listCustomerDocuments.mockResolvedValue(documents(["pl", "en"], null));
  const first = view();
  await screen.findByRole("table");
  await waitFor(() => expect(api.listCustomerDocuments).toHaveBeenCalled());
  expect(screen.queryByTestId("terms-languages-off")).toBeNull();
  first.unmount();

  api.listCustomerDocuments.mockResolvedValue(
    documents(["pl", "en"], ["en", "pl"]),
  );
  view();
  await screen.findByRole("table");
  await waitFor(() =>
    expect(api.listCustomerDocuments).toHaveBeenCalledTimes(2),
  );
  expect(screen.queryByTestId("terms-languages-off")).toBeNull();
});
