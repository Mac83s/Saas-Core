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

import type { CreditLedgerEntry } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CreditUsage } from "./credit-usage";

const { listCreditLedger } = vi.hoisted(() => ({ listCreditLedger: vi.fn() }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  listCreditLedger,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const JOB = "0199f0a0-0000-7000-8000-0000000000d1";

function entry(overrides: Partial<CreditLedgerEntry> = {}): CreditLedgerEntry {
  return {
    id: "0199f0a0-0000-7000-8000-0000000000a1",
    occurred_at: "2026-10-03T12:01:00Z",
    kind: "consumed",
    bucket: "allowance",
    amount: -3,
    balance_after: 97,
    operation_key: "translation.characters",
    operation_name: "Tłumaczenie AI",
    operation_unit: "1000_characters",
    operation_quantity: 3,
    subject: { kind: "translation.job", id: JOB },
    reason: "",
    ...overrides,
  };
}

const TURN = entry({
  id: "0199f0a0-0000-7000-8000-0000000000a2",
  amount: -1,
  bucket: "purchased",
  operation_key: "assistant.conversation_turn",
  operation_name: "Rozmowa z asystentem",
  operation_unit: "operation",
  operation_quantity: 1,
  subject: null,
});

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <CreditUsage />
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
  listCreditLedger.mockResolvedValue({ items: [], next_cursor: null });
});

test("lists what used credits: the operation, the amount, the credits, the pool, the date — and the way to a translation's job", async () => {
  listCreditLedger.mockResolvedValue({
    items: [entry(), TURN],
    next_cursor: null,
  });
  const { container } = view();

  const table = await screen.findByRole("table", { name: "Zużycie" });
  const [translation, turn] = within(table).getAllByRole("row").slice(1);
  expect(translation!.textContent).toContain("Tłumaczenie AI");
  expect(translation!.textContent).toContain("3 tys. znaków");
  expect(translation!.textContent).toContain("−3");
  expect(translation!.textContent).toContain("Z planu");
  expect(translation!.textContent).toContain("3 paź 2026, 14:01");
  expect(
    within(translation!)
      .getByRole("link", { name: "Otwórz zadanie tłumaczenia" })
      .getAttribute("href"),
  ).toBe(`/panel/sites/translations/jobs/${JOB}`);
  // One turn of the assistant: no amount to say and nothing to open.
  expect(turn!.textContent).toContain("Rozmowa z asystentem");
  expect(turn!.textContent).toContain("Dokupione");
  expect(within(turn!).queryByRole("link")).toBeNull();
  // What was used is the server's filter.
  expect(listCreditLedger).toHaveBeenCalledWith({
    limit: 25,
    kind: "consumed",
  });
  await expectNoAxeViolations(container);
});

test("„Wszystkie ruchy” asks the server for every kind and names each in words", async () => {
  view();
  await screen.findByText("Nic jeszcze nie zużyło kredytów.");
  listCreditLedger.mockResolvedValue({
    items: [
      entry({
        id: "g",
        kind: "allowance_granted",
        amount: 1000,
        operation_key: "",
        operation_name: "",
        operation_unit: "",
        operation_quantity: null,
        subject: null,
      }),
      entry({ id: "r", kind: "refunded", amount: 2, subject: null }),
      entry({
        id: "o",
        kind: "operator_adjustment",
        amount: 50,
        bucket: "purchased",
        operation_key: "",
        operation_name: "",
        operation_unit: "",
        operation_quantity: null,
        subject: null,
        reason: "Rekompensata za awarię",
      }),
      // An operation the panel has no words for keeps the catalogue's name.
      entry({
        id: "x",
        operation_key: "seo.audit",
        operation_name: "Audyt SEO",
        operation_unit: "operation",
        operation_quantity: 1,
        subject: null,
      }),
    ],
    next_cursor: null,
  });
  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "all" },
  });
  const table = await screen.findByRole("table", { name: "Zużycie" });
  await waitFor(() =>
    expect(listCreditLedger).toHaveBeenLastCalledWith({ limit: 25 }),
  );
  const text = await waitFor(() => {
    const content = table.textContent ?? "";
    expect(content).toContain("Kredyty z planu na nowy miesiąc");
    return content;
  });
  expect(text).toContain("+1000");
  expect(text).toContain("Zwrot: Tłumaczenie AI");
  expect(text).toContain("Korekta operatora platformy");
  expect(text).toContain("Rekompensata za awarię");
  expect(text).toContain("Audyt SEO");
});

test("further rows come on request; a failed read offers another try", async () => {
  listCreditLedger.mockResolvedValueOnce({
    items: [entry()],
    next_cursor: "0199f0a0-0000-7000-8000-0000000000a1",
  });
  view();
  fireEvent.click(
    await screen.findByRole("button", { name: "Wczytaj więcej" }),
  );
  await waitFor(() =>
    expect(listCreditLedger).toHaveBeenLastCalledWith({
      limit: 25,
      kind: "consumed",
      cursor: "0199f0a0-0000-7000-8000-0000000000a1",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Wczytaj więcej" })).toBeNull(),
  );

  listCreditLedger.mockRejectedValueOnce(new Error("down"));
  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "all" },
  });
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Nie udało się wczytać zużycia kredytów.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(
    await screen.findByText("Nie było jeszcze żadnego ruchu kredytów."),
  ).toBeTruthy();
});

test("English words and axe", async () => {
  listCreditLedger.mockResolvedValue({ items: [entry()], next_cursor: null });
  const { container } = view("en");
  const table = await screen.findByRole("table", { name: "Usage" });
  expect(table.textContent).toContain("AI translation");
  expect(table.textContent).toContain("3k characters");
  expect(table.textContent).toContain("From the plan");
  expect(
    within(table).getByRole("link", { name: "Open the translation job" }),
  ).toBeTruthy();
  await expectNoAxeViolations(container);
});
