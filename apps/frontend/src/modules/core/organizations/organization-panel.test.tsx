import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { OrganizationPanel } from "./organization-panel";

const { getOrganizationOptions, listOrganizations, listMemberships, router } =
  vi.hoisted(() => ({
    getOrganizationOptions: vi.fn(),
    listOrganizations: vi.fn(),
    listMemberships: vi.fn(),
    router: { replace: vi.fn(), refresh: vi.fn() },
  }));

vi.mock("#i18n/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getOrganizationOptions,
  listOrganizations,
  listMemberships,
}));

beforeEach(() => {
  vi.clearAllMocks();
  getOrganizationOptions.mockResolvedValue({ keys: [] });
});

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

  expect(await screen.findByText("Aktywna: Acme")).toBeInTheDocument();
  expect(
    (screen.getByLabelText("Wybierz organizację") as HTMLInputElement).value,
  ).toBe("Acme");
  expect(listMemberships).not.toHaveBeenCalled();
});

test("nowa organizacja: pola wyboru pokazują etykiety, nie surowe wartości", async () => {
  listOrganizations.mockResolvedValue([]);
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <OrganizationPanel />
    </NextIntlClientProvider>,
  );

  fireEvent.click(
    await screen.findByRole("button", { name: /Nowa organizacja/ }),
  );

  // Read before any list has been opened: „Firmowa”, never „business”.
  expect(
    await screen.findByRole("combobox", { name: "Typ przestrzeni" }),
  ).toHaveTextContent("Firmowa");
  expect(
    screen.getByRole("combobox", { name: "Język panelu i e-maili do zespołu" }),
  ).toHaveTextContent("Polski");
});
