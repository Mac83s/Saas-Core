import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import messages from "../../../messages/pl.json";
import { SidebarProvider } from "@saas-core/ui/components/sidebar";
import { OrganizationSwitcher } from "./organization-switcher";

const { refresh, selectActiveOrganization } = vi.hoisted(() => ({
  refresh: vi.fn(),
  selectActiveOrganization: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({
  useRouter: () => ({ refresh }),
}));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  selectActiveOrganization,
}));

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

test("przełącza aktywną organizację i odświeża shell", async () => {
  selectActiveOrganization.mockResolvedValue({});
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <SidebarProvider>
        <OrganizationSwitcher
          organizations={[
            organization("org-one", "Pierwsza firma", true),
            organization("org-two", "Druga firma", false),
          ]}
          roleLabel="Właściciel"
        />
      </SidebarProvider>
    </NextIntlClientProvider>,
  );

  fireEvent.click(screen.getByRole("button", { name: /Pierwsza firma/ }));
  fireEvent.click(
    await screen.findByRole("menuitemradio", { name: "Druga firma" }),
  );

  await waitFor(() =>
    expect(selectActiveOrganization).toHaveBeenCalledWith("org-two"),
  );
  expect(refresh).toHaveBeenCalledOnce();
});

test("bez aktywnej organizacji zostaje i prosi o wybór", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <SidebarProvider>
        <OrganizationSwitcher
          organizations={[
            organization("org-one", "Pierwsza firma", false),
            organization("org-two", "Druga firma", false),
          ]}
          roleLabel=""
        />
      </SidebarProvider>
    </NextIntlClientProvider>,
  );

  expect(
    screen.getByRole("button", { name: "Wybierz organizację" }),
  ).not.toBeNull();
});

function organization(id: string, name: string, active: boolean) {
  return {
    id,
    name,
    slug: id,
    workspace_kind: "business",
    organization_type: "business",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role: "owner",
    permissions: ["organization.read"],
    active,
  };
}
