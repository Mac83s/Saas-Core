import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { RolesPanel } from "./roles-panel";

const { api, address } = vi.hoisted(() => ({
  api: {
    createRole: vi.fn(),
    deleteRole: vi.fn(),
    listMemberships: vi.fn(),
    listRoles: vi.fn(),
    updateRole: vi.fn(),
  },
  address: { params: new URLSearchParams() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => address.params }));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const viewer = [
  "organization.read",
  "notifications.preferences",
  "booking.appointment.read",
];
const staff = [...viewer, "organization.members.read"];
const manager = [
  ...staff,
  "organization.members.manage_limited",
  "booking.appointment.manage",
];
const admin = [
  ...manager,
  "organization.members.manage",
  "organization.settings.manage",
];

function role(key: string, permissions: string[], limited = false) {
  return {
    key,
    name: key,
    scope: "system" as const,
    permissions,
    limited,
    version: 1,
  };
}

function organization(permissions: string[]): OrganizationSummary {
  return {
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
    role: "admin",
    permissions,
    active: true,
  };
}

const own = {
  ...role("custom-1a2b", [
    "organization.read",
    "booking.appointment.read",
    "booking.appointment.manage",
  ]),
  name: "Biuro",
  scope: "organization" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  address.params = new URLSearchParams();
  api.listRoles.mockResolvedValue({
    roles: [
      role("admin", admin),
      role("manager", manager),
      role("staff", staff, true),
      own,
    ],
    grantable_permissions: manager,
  });
  api.listMemberships.mockResolvedValue([
    { role: "admin" },
    { role: "staff" },
    { role: "staff" },
  ]);
  api.createRole.mockResolvedValue({});
  api.updateRole.mockResolvedValue({});
  api.deleteRole.mockResolvedValue(undefined);
});

afterEach(cleanup);

function renderPanel(
  permissions = [...admin, "organization.members.manage"],
  locale: "pl" | "en" = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <RolesPanel organization={organization(permissions)} />
    </NextIntlClientProvider>,
  );
}

test("role jako lista: co może, ile osób, zarządzające i własne oznaczone", async () => {
  const { container } = renderPanel();
  const table = await screen.findByRole("table", {
    name: "Role w organizacji",
  });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(4);
  expect(within(rows[0]).getByText("Administrator")).toBeInTheDocument();
  expect(within(rows[0]).getByText("Zarządza")).toBeInTheDocument();
  expect(
    within(rows[0]).getByText("Pełny dostęp do wszystkiego."),
  ).toBeInTheDocument();
  expect(within(rows[2]).getByText("2")).toBeInTheDocument();
  const biuro = rows.find((row) => within(row).queryByText("Biuro"))!;
  expect(within(biuro).getByText("Własna")).toBeInTheDocument();
  expect(
    within(biuro).getByText(
      "Edycja: kalendarz i wizyty. Bez dostępu: zespół, ustawienia organizacji.",
    ),
  ).toBeInTheDocument();
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("utwórz rolę prosto z dialogu roli osoby (?new=1), edytuj i usuń własną", async () => {
  address.params = new URLSearchParams("new=1");
  renderPanel();
  const dialog = await screen.findByRole("dialog", { name: "Nowa rola" });
  fireEvent.change(within(dialog).getByLabelText("Nazwa roli"), {
    target: { value: "Brygadzista" },
  });
  fireEvent.click(within(dialog).getByLabelText("Zarządzanie wizytami"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz rolę" }));
  await waitFor(() =>
    expect(api.createRole).toHaveBeenCalledWith({
      name: "Brygadzista",
      permissions: ["booking.appointment.manage"],
    }),
  );
  expect(
    await screen.findByText("Zapisano rolę: Brygadzista."),
  ).toBeInTheDocument();

  fireEvent.click(
    await screen.findByRole("button", { name: "Działania: Biuro" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń" }));
  await waitFor(() =>
    expect(api.deleteRole).toHaveBeenCalledWith("custom-1a2b"),
  );
});

test("bez zarządzania zespołem role są tylko do odczytu (EN)", async () => {
  renderPanel(manager, "en");
  await screen.findByRole("table", { name: "The organization's roles" });
  expect(screen.queryByRole("button", { name: "New role" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Actions: Biuro" })).toBeNull();
});
