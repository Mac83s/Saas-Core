import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { EntitlementSupportPanel } from "./entitlement-support-panel";

const { getEntitlementSupportReport } = vi.hoisted(() => ({
  getEntitlementSupportReport: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getEntitlementSupportReport,
}));

beforeEach(() => vi.clearAllMocks());

test("wyjaśnia decyzję i źródło z lokalnego snapshotu", async () => {
  getEntitlementSupportReport.mockResolvedValue({
    snapshot: {
      id: "019c5f87-fce8-739b-b960-b7a195bfc298",
      version: 4,
      subscription_state: "active",
      access_mode: "full",
      plan_key: "starter",
      plan_version: 1,
      computed_at: "2026-08-11T12:00:00Z",
      effective_until: null,
    },
    items: [
      {
        kind: "feature",
        key: "booking.enabled",
        available: true,
        reason: "allowed",
        read_allowed: true,
        read_reason: "allowed",
        value: null,
        used: null,
        reserved: null,
        period_start: null,
        period_end: null,
        evidence: { kind: "plan", ref: "starter:v1" },
      },
    ],
  });

  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <EntitlementSupportPanel />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("starter v1")).not.toBeNull();
  expect(screen.getByText("booking.enabled")).not.toBeNull();
  expect(screen.getByText("Wersja planu")).not.toBeNull();
  expect(screen.getByText("starter:v1")).not.toBeNull();
  expect(getEntitlementSupportReport).toHaveBeenCalledOnce();
});
