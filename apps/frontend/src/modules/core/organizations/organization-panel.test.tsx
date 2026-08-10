import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { OrganizationPanel } from "./organization-panel";

const { listOrganizations, listMemberships, listInvitations, router } =
  vi.hoisted(() => ({
    listOrganizations: vi.fn(),
    listMemberships: vi.fn(),
    listInvitations: vi.fn(),
    router: { replace: vi.fn(), refresh: vi.fn() },
  }));

vi.mock("#i18n/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  listOrganizations,
  listMemberships,
  listInvitations,
}));

beforeEach(() => vi.clearAllMocks());

test("ładuje aktywną organizację, członków i zaproszenia", async () => {
  listOrganizations.mockResolvedValue([
    {
      id: "019c5f87-fce8-739b-b960-b7a195bfc298",
      name: "Acme",
      slug: "acme",
      workspace_kind: "business",
      status: "active",
      default_locale: "pl",
      timezone: "Europe/Warsaw",
      currency: "PLN",
      version: 1,
      membership_status: "active",
      role: "owner",
      active: true,
    },
  ]);
  listMemberships.mockResolvedValue([
    {
      id: "019c5f87-fce8-739b-b960-b7a195bfc299",
      user_id: "019c5f87-fce8-739b-b960-b7a195bfc300",
      email: "owner@example.com",
      role: "owner",
      status: "active",
      joined_at: "2026-08-10T12:00:00Z",
    },
  ]);
  listInvitations.mockResolvedValue([]);

  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <OrganizationPanel />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("owner@example.com")).not.toBeNull();
  expect(
    (screen.getByLabelText("Wybierz organizację") as HTMLInputElement).value,
  ).toBe("Acme");
  expect(screen.getByText("Właściciel")).not.toBeNull();
  expect(listMemberships).toHaveBeenCalledOnce();
  expect(listInvitations).toHaveBeenCalledOnce();
});
