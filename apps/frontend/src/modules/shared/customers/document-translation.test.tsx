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
  CustomerDocument,
  CustomerDocumentOptions,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CustomerDocumentPanel } from "./document-panel";

const { api } = vi.hoisted(() => ({
  api: {
    readCustomerDocument: vi.fn(),
    getTranslationOffer: vi.fn(),
    quoteTranslation: vi.fn(),
    orderTranslation: vi.fn(),
  },
}));
// The document's screen offers a machine translation: the engine is composed.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const DOCUMENT = "0199a000-0000-7000-8000-0000000000d1";
const options = {
  kinds: ["booking_terms", "shop_terms", "privacy_policy"],
  locales: ["pl", "en", "de"],
  default_locale: "pl",
  text_max: 100000,
} as unknown as CustomerDocumentOptions;

function version(number: number, effective: string) {
  return {
    number,
    source_locale: "pl",
    effective_from: effective,
    approved_at: "2026-10-03T10:00:00Z",
    approved_by: "Daria Dokumentowa",
    locales: ["pl"],
    texts: [
      {
        id: `0199a000-0000-7000-8000-00000000000${number}`,
        locale: "pl",
        text: "Regulamin sklepu.",
        text_hash: "a".repeat(64),
        accepted_at: "2026-10-03T10:00:00Z",
        accepted_by: "Daria Dokumentowa",
      },
    ],
  };
}

function terms(overrides: Partial<CustomerDocument> = {}): CustomerDocument {
  return {
    kind: "shop_terms",
    version: 4,
    draft: null,
    in_force: version(1, "2026-10-03"),
    upcoming: null,
    public_url: "http://business.localhost:8080/documents/abc",
    versions: [version(1, "2026-10-03")],
    translation: { object_id: DOCUMENT, version: 1, waiting: [] },
    ...overrides,
  } as CustomerDocument;
}

function show(canManage = true, locale: "pl" | "en" = "pl", website?: boolean) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <CustomerDocumentPanel
        canManage={canManage}
        kind="shop_terms"
        website={website}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getTranslationOffer.mockResolvedValue({ available: true, reasons: [] });
  api.readCustomerDocument.mockResolvedValue({ document: terms(), options });
});

test("the missing languages are ordered for the document, and the result is said to wait for acceptance", async () => {
  api.quoteTranslation.mockResolvedValue({ units: 1, credits: 2 });
  api.orderTranslation.mockResolvedValue({});
  show();

  const section = await screen.findByRole("region", { name: /^Wersja 1 od/ });
  expect(section.textContent).toContain(
    "Tłumaczenie dokumentu nigdy nie trafia do klientów samo",
  );
  expect(
    within(section)
      .getByRole("link", { name: "Tłumaczenia → Do akceptacji" })
      .getAttribute("href"),
  ).toBe("/panel/sites/translations/review");

  fireEvent.click(
    await within(section).findByRole("button", {
      name: "Przetłumacz brakujące",
    }),
  );
  // Every other language of the company, against this document.
  const targets = ["en", "de"].map((locale) => ({
    source_key: "customers.document",
    object_id: DOCUMENT,
    locale,
    basis: "published",
  }));
  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith(targets),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Przetłumaczyć brakujące teksty?",
  });
  expect(dialog.textContent).toContain("Zużyje 2 kredyty.");
  fireEvent.click(within(dialog).getByRole("button", { name: "Przetłumacz" }));

  await waitFor(() =>
    expect(api.orderTranslation).toHaveBeenCalledWith(
      targets,
      { units: 1, credits: 2 },
      expect.any(String),
    ),
  );
  expect(
    await within(section).findByText(/poczeka w „Tłumaczenia → Do akceptacji”/),
  ).toBeTruthy();
  // The document is read again: what waits shows once the job has delivered.
  await waitFor(() =>
    expect(api.readCustomerDocument).toHaveBeenCalledTimes(2),
  );
});

test("without websites the way to accept is named by what it holds, not by a menu the company lacks", async () => {
  show(true, "pl", false);

  const section = await screen.findByRole("region", { name: /^Wersja 1 od/ });
  // „Tłumaczenia” is an entry of „Strona internetowa”: no such path here.
  expect(
    within(section).queryByRole("link", {
      name: "Tłumaczenia → Do akceptacji",
    }),
  ).toBeNull();
  expect(
    within(section)
      .getByRole("link", { name: "Tłumaczenia do akceptacji" })
      .getAttribute("href"),
  ).toBe("/panel/sites/translations/review");
});

test("a translation that waits is said beside its language, with the way to accept it", async () => {
  api.readCustomerDocument.mockResolvedValue({
    document: terms({
      translation: { object_id: DOCUMENT, version: 1, waiting: ["en"] },
    } as Partial<CustomerDocument>),
    options,
  });
  show();

  const waits = await screen.findByText(
    /Tłumaczenie AI \(English\) czeka na Twoją akceptację\./,
  );
  expect(within(waits).getByRole("link").getAttribute("href")).toBe(
    "/panel/sites/translations/review",
  );
  expect(screen.queryByText(/Tłumaczenie AI \(Deutsch\)/)).toBeNull();

  // What waits is not ordered — and paid for — again: only German is asked.
  api.quoteTranslation.mockResolvedValue({ units: 0, credits: 0 });
  fireEvent.click(
    await screen.findByRole("button", { name: "Przetłumacz brakujące" }),
  );
  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith([
      {
        source_key: "customers.document",
        object_id: DOCUMENT,
        locale: "de",
        basis: "published",
      },
    ]),
  );
  expect(
    await screen.findByText("Wszystko jest już przetłumaczone."),
  ).toBeTruthy();
});

test("the order stands in the version that is translated: the one approved for a later day", async () => {
  api.readCustomerDocument.mockResolvedValue({
    document: terms({
      upcoming: version(2, "2026-11-01"),
      versions: [version(2, "2026-11-01"), version(1, "2026-10-03")],
      translation: { object_id: DOCUMENT, version: 2, waiting: [] },
    } as Partial<CustomerDocument>),
    options,
  });
  show(true, "en");

  const buttons = await screen.findAllByRole("button", {
    name: "Translate what is missing",
  });
  expect(buttons).toHaveLength(1);
  const upcoming = screen.getByRole("region", { name: /version 2$/ });
  expect(upcoming.contains(buttons[0]!)).toBe(true);
});

test("whoever only reads the documents, and a deployment's offer that is off, get no order button", async () => {
  const reader = show(false);
  await screen.findByRole("region", { name: /^Wersja 1 od/ });
  expect(screen.queryByText("Przetłumacz brakujące")).toBeNull();
  expect(api.getTranslationOffer).not.toHaveBeenCalled();
  reader.unmount();

  api.getTranslationOffer.mockResolvedValue({
    available: false,
    reasons: ["model_not_selected"],
  });
  show();
  expect(
    await screen.findByText(/Automatyczne tłumaczenie będzie dostępne/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Przetłumacz brakujące" }),
  ).toBeNull();
});
