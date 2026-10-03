import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type TranslationJob,
  type TranslationOffer,
  type TranslationQuote,
} from "@saas-core/api-client";

import messages from "../../../../messages/pl.json";
import { TranslateDialog, TranslationUnavailable } from "./translate-dialog";

const api = vi.hoisted(() => ({
  quoteTranslation: vi.fn(),
  orderTranslation: vi.fn(),
  getCustomerCredits: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const TARGET = {
  source_key: "sites.page",
  object_id: "019ff20d-a000-7000-8000-000000000001",
  locale: "de",
  basis: "published" as const,
};
const OFFER = {
  available: true,
  reasons: [],
  billing: { mode: "credits" },
} as unknown as TranslationOffer;

function line(extra: Partial<TranslationQuote["lines"][number]> = {}) {
  return {
    source_key: "sites.page",
    object_id: TARGET.object_id,
    locale: "de",
    basis: "published",
    characters: 1840,
    proposals: 0,
    proposal_characters: 0,
    skipped: {},
    outcome: "live",
    reason: null,
    excluded: null,
    ...extra,
  };
}

function quote(extra: Partial<TranslationQuote> = {}): TranslationQuote {
  return {
    digest: "d".repeat(64),
    available: true,
    reasons: [],
    characters: 1840,
    units: 2,
    unit_cost: 1,
    credits: 2,
    mode: "automatic",
    protected: "propose",
    include_unverified: false,
    parts: [[0]],
    waiting: {},
    lines: [line()],
    ...extra,
  } as TranslationQuote;
}

function show(
  props: Partial<Parameters<typeof TranslateDialog>[0]> = {},
  onOrdered = vi.fn(),
) {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslateDialog
        open
        onOpenChange={vi.fn()}
        targets={[TARGET]}
        languageName={() => "Deutsch"}
        reasonText={(reason) => `powód ${reason}`}
        offer={OFFER}
        onOrdered={onOrdered}
        {...props}
      />
    </NextIntlClientProvider>,
  );
  return onOrdered;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getCustomerCredits.mockResolvedValue({ balance: { available: 10 } });
});

test("says how much, what it costs against the balance and where it lands, then orders", async () => {
  api.quoteTranslation.mockResolvedValue(quote());
  api.orderTranslation.mockResolvedValue({ id: "job-1", state: "queued" });
  const ordered = show();

  expect(await screen.findByText(/Do przetłumaczenia: 1840 znaków/)).not.toBeNull();
  expect(screen.getByText(/Koszt: 2 kredyty\. Masz 10 kredytów\./)).not.toBeNull();
  expect(
    screen.getByText("Gotowe tłumaczenie trafi na stronę od razu."),
  ).not.toBeNull();
  expect((await axe.run(document.body)).violations).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "Przetłumacz" }));
  await waitFor(() => expect(api.orderTranslation).toHaveBeenCalledOnce());
  expect(api.orderTranslation.mock.calls[0]).toEqual([
    [TARGET],
    expect.objectContaining({ digest: "d".repeat(64), credits: 2 }),
    expect.any(String),
    "propose",
  ]);
  expect(ordered).toHaveBeenCalledWith({ id: "job-1", state: "queued" });
});

test("too few credits says how many are missing and does not order", async () => {
  api.quoteTranslation.mockResolvedValue(quote({ credits: 14, units: 14 }));
  show();

  expect(
    await screen.findByText(/Brakuje 4 kredytów\. Dokupisz je w Abonament › Kredyty\./),
  ).not.toBeNull();
  expect(
    (screen.getByRole("button", { name: "Przetłumacz" }) as HTMLButtonElement).disabled,
  ).toBe(true);
});

test("the person's corrections stay unless they choose to overwrite them", async () => {
  api.quoteTranslation
    .mockResolvedValueOnce(
      quote({
        waiting: { overwrites_human: 1 },
        lines: [line({ proposals: 3, outcome: "pending", reason: "overwrites_human" })],
      }),
    )
    .mockResolvedValueOnce(quote({ protected: "overwrite" }));
  show();

  expect(
    await screen.findByText(
      "Gotowe tłumaczenie poczeka na Twoją akceptację: powód overwrites_human.",
    ),
  ).not.toBeNull();
  fireEvent.click(screen.getByLabelText("Nadpisz też moje poprawki (3)"));

  await waitFor(() => expect(api.quoteTranslation).toHaveBeenCalledTimes(2));
  expect(api.quoteTranslation.mock.calls[1]?.[1]).toBe("overwrite");
});

test("a page never published is translated from the editor's version", async () => {
  api.quoteTranslation
    .mockResolvedValueOnce(
      quote({
        characters: 0,
        units: 0,
        credits: 0,
        lines: [line({ characters: 0, excluded: "source_unpublished" })],
      }),
    )
    .mockResolvedValueOnce(quote({ lines: [line({ basis: "working", outcome: "draft" })] }));
  show({ allowWorking: true });

  expect(
    await screen.findByText(/tłumaczę wersję z edytora/),
  ).not.toBeNull();
  expect(api.quoteTranslation.mock.calls[1]?.[0]).toEqual([
    { ...TARGET, basis: "working" },
  ]);
  expect(
    screen.getByText(/zostanie w edytorze — na stronę trafi z Twoją publikacją/),
  ).not.toBeNull();
});

test("a quote that went stale is asked for again, and nothing to do is said so", async () => {
  api.quoteTranslation
    .mockResolvedValueOnce(quote())
    .mockResolvedValueOnce(quote({ characters: 0, units: 0, credits: 0, lines: [] }));
  api.orderTranslation.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "translation_quote_changed",
      detail: "",
      correlation_id: null,
    }),
  );
  show();

  fireEvent.click(await screen.findByRole("button", { name: "Przetłumacz" }));
  expect(
    await screen.findByText("Nie ma nic do przetłumaczenia — wszystko jest aktualne."),
  ).not.toBeNull();
  expect(screen.getByText(/Treść zmieniła się od wyceny/)).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Przetłumacz" })).toBeNull();
});

test("a running order says the window may be closed, a finished one how it ended", () => {
  const running = { id: "job-1", state: "running" } as TranslationJob;
  const { rerender } = render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslateDialog
        open
        onOpenChange={vi.fn()}
        targets={[TARGET]}
        languageName={() => "Deutsch"}
        reasonText={(reason) => reason}
        offer={OFFER}
        job={running}
        onOrdered={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
  expect(screen.getByText(/Możesz zamknąć to okno/)).not.toBeNull();
  expect(api.quoteTranslation).not.toHaveBeenCalled();

  rerender(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslateDialog
        open
        onOpenChange={vi.fn()}
        targets={[TARGET]}
        languageName={() => "Deutsch"}
        reasonText={(reason) => reason}
        offer={OFFER}
        job={{ ...running, state: "partial" } as TranslationJob}
        onOrdered={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
  expect(screen.getByText(/gotowe częściowo/)).not.toBeNull();
});

test("an engine that takes no orders says why in the customer's words", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslationUnavailable reasons={["operation_unpriced", "model_not_selected"]} />
    </NextIntlClientProvider>,
  );
  expect(
    screen.getByText(
      "Automatyczne tłumaczenie nie jest teraz dostępne: platforma nie ustaliła jeszcze ceny tłumaczeń. Możesz przetłumaczyć ręcznie.",
    ),
  ).not.toBeNull();
});
