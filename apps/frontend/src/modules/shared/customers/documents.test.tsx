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
  type CustomerDocument,
  type CustomerDocumentList,
} from "@saas-core/api-client";
import polishMessages from "../../../../messages/pl.json";
import { CustomerDocumentPanel } from "./document-panel";
import { CustomerDocumentsPanel } from "./documents-panel";

const { api } = vi.hoisted(() => ({
  api: {
    listCustomerDocuments: vi.fn(),
    readCustomerDocument: vi.fn(),
    saveCustomerDocumentDraft: vi.fn(),
    previewCustomerDocumentApproval: vi.fn(),
    approveCustomerDocument: vi.fn(),
    addCustomerDocumentText: vi.fn(),
    confirmStepUp: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const options = {
  kinds: [
    "booking_terms",
    "shop_terms",
    "privacy_policy",
    "cancellation_policy",
  ],
  locales: ["pl", "en"],
  default_locale: "pl",
  text_max: 100000,
} as CustomerDocumentList["options"];

const version = {
  number: 2,
  source_locale: "pl",
  effective_from: "2026-10-03",
  approved_at: "2026-10-03T10:00:00Z",
  approved_by: "Ola Właścicielka",
  locales: ["pl"],
  texts: [
    {
      id: "0199a000-0000-7000-8000-000000000001",
      locale: "pl",
      text: "Administratorem danych jest Studio.",
      text_hash: "a".repeat(64),
      accepted_at: "2026-10-03T10:00:00Z",
      accepted_by: "Ola Właścicielka",
    },
  ],
};

function privacy(overrides: Partial<CustomerDocument> = {}): CustomerDocument {
  return {
    kind: "privacy_policy",
    version: 5,
    draft: null,
    in_force: version,
    upcoming: null,
    public_url: "http://business.localhost:8080/documents/abc",
    versions: [version],
    ...overrides,
  } as CustomerDocument;
}

function empty(kind: CustomerDocument["kind"]): CustomerDocument {
  return {
    kind,
    version: 0,
    draft: null,
    in_force: null,
    upcoming: null,
    public_url: null,
  } as CustomerDocument;
}

function wrap(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      {node}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listCustomerDocuments.mockResolvedValue({
    documents: [
      empty("booking_terms"),
      empty("shop_terms"),
      privacy({ draft: { text: "Nowa treść", locale: "pl", origin_ref: "" } }),
      empty("cancellation_policy"),
    ],
    options,
  });
  api.readCustomerDocument.mockResolvedValue({ document: privacy(), options });
});

test("the list says what is in force, in which languages, and where a draft waits", async () => {
  const { container } = wrap(<CustomerDocumentsPanel />);

  const table = await screen.findByRole("table", {
    name: "Dokumenty firmy dla klientów",
  });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(
    rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent),
  ).toEqual([
    "Regulamin rezerwacji",
    "Regulamin sklepu",
    "Polityka prywatności",
    "Polityka anulowania",
  ]);
  expect(within(rows[0]!).getByText("Brak zatwierdzonej wersji")).toBeTruthy();
  expect(within(rows[2]!).getByText(/Wersja 2 od 3 paź 2026/)).toBeTruthy();
  // A language of the company the version has no text in is named.
  expect(within(rows[2]!).getByText("brak: EN")).toBeTruthy();
  expect(within(rows[2]!).getByText("Szkic czeka")).toBeTruthy();
  expect(
    within(rows[2]!)
      .getByRole("link", { name: "Polityka prywatności" })
      .getAttribute("href"),
  ).toBe("/panel/settings/documents/privacy_policy");
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("a draft is saved at the version read and approved after the preview and the code", async () => {
  const drafted = privacy({
    version: 6,
    draft: { text: "Nowa treść polityki.", locale: "pl", origin_ref: "" },
  });
  api.saveCustomerDocumentDraft.mockResolvedValue(drafted);
  api.previewCustomerDocumentApproval.mockResolvedValue({
    effect: {
      number: 3,
      effective_from: "2026-10-03",
      source_locale: "pl",
      locales_without_text: ["en"],
    },
    document: drafted,
  });
  api.approveCustomerDocument
    .mockRejectedValueOnce(
      new ApiProblemError({
        status: 403,
        code: "step_up_required",
        title: "",
        detail: "Potwierdź kodem.",
      } as never),
    )
    .mockResolvedValue({
      effect: { number: 3 },
      document: privacy({ version: 7 }),
    });
  api.confirmStepUp.mockResolvedValue(undefined);
  const { container } = wrap(
    <CustomerDocumentPanel canManage kind="privacy_policy" />,
  );

  const draft = await screen.findByRole("region", { name: "Szkic" });
  fireEvent.change(within(draft).getByLabelText("Treść"), {
    target: { value: "Nowa treść polityki." },
  });
  fireEvent.click(within(draft).getByRole("button", { name: "Zatwierdź…" }));

  const dialog = await screen.findByRole("dialog", {
    name: "Zatwierdzić dokument?",
  });
  expect(api.saveCustomerDocumentDraft).toHaveBeenCalledWith("privacy_policy", {
    text: "Nowa treść polityki.",
    locale: "pl",
    expected_version: 5,
  });
  expect(api.previewCustomerDocumentApproval).toHaveBeenCalledWith(
    "privacy_policy",
    { expected_version: 6 },
  );
  // The preview names the languages whose readers will see no document.
  expect(within(dialog).getByText(/w językach: English/)).toBeTruthy();
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);

  fireEvent.click(within(dialog).getByRole("button", { name: "Zatwierdź" }));
  const stepUp = await screen.findByRole("dialog", {
    name: polishMessages.StepUp.title,
  });
  fireEvent.change(within(stepUp).getByLabelText(polishMessages.StepUp.code), {
    target: { value: "123456" },
  });
  fireEvent.click(
    within(stepUp).getByRole("button", { name: polishMessages.StepUp.confirm }),
  );

  await waitFor(() =>
    expect(api.approveCustomerDocument).toHaveBeenCalledTimes(2),
  );
  expect(api.approveCustomerDocument.mock.calls[1]).toEqual([
    "privacy_policy",
    { expected_version: 6, effective_from: "2026-10-03" },
  ]);
  expect(await screen.findByText("Wersja 3 zatwierdzona.")).toBeTruthy();
});

test("a missing language of the version in force gets its text as a new row", async () => {
  api.addCustomerDocumentText.mockResolvedValue(
    privacy({ version: 6, in_force: { ...version, locales: ["en", "pl"] } }),
  );
  wrap(<CustomerDocumentPanel canManage kind="privacy_policy" />);

  const section = await screen.findByRole("region", {
    name: /Wersja 2 od 3 paź 2026/,
  });
  expect(
    within(section).getByText(
      "Klienci, którzy czytają w języku English, nie widzą tego dokumentu.",
    ),
  ).toBeTruthy();
  fireEvent.click(
    within(section).getByRole("button", { name: "Dodaj tekst: English" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "English — wersja 2",
  });
  fireEvent.change(within(dialog).getByLabelText("Treść"), {
    target: { value: "The controller is Studio." },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz tekst" }));

  await waitFor(() =>
    expect(api.addCustomerDocumentText).toHaveBeenCalledWith("privacy_policy", {
      number: 2,
      locale: "en",
      text: "The controller is Studio.",
      expected_version: 5,
    }),
  );
  expect(await screen.findByText("Tekst zapisany: English.")).toBeTruthy();
});

test("who only reads sees the versions and no way to write", async () => {
  wrap(<CustomerDocumentPanel canManage={false} kind="privacy_policy" />);

  await screen.findByRole("region", { name: /Wersja 2 od 3 paź 2026/ });
  expect(screen.queryByRole("region", { name: "Szkic" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Dodaj tekst/ })).toBeNull();
  expect(screen.getByRole("table", { name: "Wersje" })).toBeTruthy();
});
