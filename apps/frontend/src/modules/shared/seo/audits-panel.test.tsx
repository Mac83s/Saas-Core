import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiProblemError, type SeoAuditOrder } from "@saas-core/api-client";

import pl from "../../../../messages/pl.json";
import en from "../../../../messages/en.json";
import { SeoAuditsPanel } from "./audits-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const api = vi.hoisted(() => ({
  getSeoAuditOffer: vi.fn(),
  listSeoAudits: vi.fn(),
  listSites: vi.fn(),
  readSeoAudit: vi.fn(),
  requestSeoAudit: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const order: SeoAuditOrder = {
  id: "019ff20d-d000-7000-8000-000000000001",
  site_id: "019ff20d-d000-7000-8000-000000000002",
  state: "completed",
  requested_options: { max_pages: 100 },
  effective_options: { max_pages: 100 },
  credit_cost: 7,
  credit_state: "committed",
  report_hash: "hash",
  error_code: "",
  created_at: "2026-09-06T12:00:00Z",
  updated_at: "2026-09-06T12:01:00Z",
  completed_at: "2026-09-06T12:01:00Z",
  report_snapshot: {
    score: { overall_score: 82 },
    provenance: { observed_at: "2026-09-06T12:01:00Z" },
    issues: [
      {
        id: "issue-1",
        rule_code: "TITLE_MISSING",
        page_url: "https://example.test/about",
        severity: "high",
      },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getSeoAuditOffer.mockResolvedValue({ credit_cost: 7, max_pages: 100 });
  api.listSeoAudits.mockResolvedValue({ items: [order], next_cursor: null });
  api.listSites.mockResolvedValue({
    items: [{ id: order.site_id, name: "Example website" }],
    next_cursor: null,
  });
  api.readSeoAudit.mockResolvedValue(order);
  api.requestSeoAudit.mockResolvedValue({
    ...order,
    state: "queued",
    credit_state: "reserved",
    report_hash: "",
    report_snapshot: {},
  });
});
afterEach(cleanup);

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? pl : en}
    >
      <main>
        <SeoAuditsPanel />
      </main>
    </NextIntlClientProvider>,
  );
}

test.each(["pl", "en"] as const)(
  "retained audit is readable and accessible in %s without reordering",
  async (locale) => {
    const { container } = view(locale);
    fireEvent.click(
      await screen.findByRole("button", {
        name: locale === "pl" ? "Otwórz wynik" : "Open result",
      }),
    );
    expect(await screen.findByText("TITLE_MISSING")).toBeInTheDocument();
    expect(screen.getByText("82/100")).toBeInTheDocument();
    expect(api.requestSeoAudit).not.toHaveBeenCalled();
    expect((await axe.run(container)).violations).toEqual([]);
  },
);

test("order submits the shown price and one key survives an unknown response and refresh", async () => {
  api.requestSeoAudit.mockRejectedValueOnce(new Error("network lost"));
  view();
  const choose = await screen.findByLabelText("Strona internetowa");
  fireEvent.change(choose, { target: { value: order.site_id } });
  fireEvent.click(screen.getByRole("button", { name: "Zamów za 7 kredytów" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się potwierdzić zamówienia",
  );
  const first = api.requestSeoAudit.mock.calls[0][0];
  expect(first).toMatchObject({
    expected_credit_cost: 7,
    max_pages: 100,
    site_id: order.site_id,
  });
  api.getSeoAuditOffer.mockResolvedValue({ credit_cost: 9, max_pages: 100 });
  fireEvent.click(screen.getByRole("button", { name: "Odśwież" }));
  await waitFor(() => expect(api.getSeoAuditOffer).toHaveBeenCalledTimes(2));
  expect(choose).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Zamów za 7 kredytów" }));
  await waitFor(() => expect(api.requestSeoAudit).toHaveBeenCalledTimes(2));
  expect(api.requestSeoAudit.mock.calls[1][0]).toEqual(first);
  expect(
    await screen.findByText("Zarezerwowano 7 kredytów"),
  ).toBeInTheDocument();
});

test("a changed price requires another explicit click and does not auto-order", async () => {
  api.requestSeoAudit.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      correlation_id: null,
      title: "Price changed",
      status: 409,
      code: "credit_price_changed",
      detail: "Changed",
    }),
  );
  view();
  fireEvent.change(await screen.findByLabelText("Strona internetowa"), {
    target: { value: order.site_id },
  });
  api.getSeoAuditOffer.mockResolvedValue({ credit_cost: 9, max_pages: 100 });
  fireEvent.click(screen.getByRole("button", { name: "Zamów za 7 kredytów" }));
  expect(
    await screen.findByRole("button", { name: "Zamów za 9 kredytów" }),
  ).toBeInTheDocument();
  expect(api.requestSeoAudit).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert")).toHaveTextContent("Cena się zmieniła");
});

test("a reader without purchasing permission can still inspect retained results", async () => {
  api.getSeoAuditOffer.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      correlation_id: null,
      title: "Forbidden",
      status: 403,
      code: "permission_denied",
      detail: "Denied",
    }),
  );
  view();
  fireEvent.click(await screen.findByRole("button", { name: "Otwórz wynik" }));
  expect(await screen.findByText("TITLE_MISSING")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Zamów za/ }),
  ).not.toBeInTheDocument();
  expect(api.requestSeoAudit).not.toHaveBeenCalled();
});

test("partial result states that credits were released and renders bounded issue rows", async () => {
  api.readSeoAudit.mockResolvedValue({
    ...order,
    state: "partial",
    credit_state: "released",
    report_snapshot: {
      issues: Array.from({ length: 101 }, (_, i) => ({
        id: String(i),
        rule_code: `ISSUE_${i}`,
        page_url: "https://example.test/",
        severity: "low",
      })),
    },
  });
  view();
  fireEvent.click(await screen.findByRole("button", { name: "Otwórz wynik" }));
  expect(await screen.findByText(/To wynik częściowy/)).toBeInTheDocument();
  expect(screen.getByText("Zwolniono 7 kredytów")).toBeInTheDocument();
  expect(screen.queryByText("ISSUE_100")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Pokaż kolejne problemy" }),
  );
  expect(screen.getByText("ISSUE_100")).toBeInTheDocument();
});
