import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { OrganizationPanel } from "./organization-panel";

const { listOrganizations, listMemberships, router } = vi.hoisted(() => ({
  listOrganizations: vi.fn(),
  listMemberships: vi.fn(),
  router: { replace: vi.fn(), refresh: vi.fn() },
}));

vi.mock("#i18n/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  listOrganizations,
  listMemberships,
}));

beforeEach(() => vi.clearAllMocks());

test("ładuje organizacje; zespołem zajmuje się TeamPanel", async () => {
  listOrganizations.mockResolvedValue([
    {
      id: "019c5f87-fce8-739b-b960-b7a195bfc298",
      name: "Acme",
      slug: "acme",
      workspace_kind: "business",
      organization_type: "business",
      status: "active",
      default_locale: "pl",
      timezone: "Europe/Warsaw",
      currency: "PLN",
      version: 1,
      membership_status: "active",
      role: "owner",
      permissions: [],
      active: true,
    },
  ]);

  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <OrganizationPanel />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("Aktywna: acme")).toBeInTheDocument();
  expect(
    (screen.getByLabelText("Wybierz organizację") as HTMLInputElement).value,
  ).toBe("Acme");
  expect(listMemberships).not.toHaveBeenCalled();
});
