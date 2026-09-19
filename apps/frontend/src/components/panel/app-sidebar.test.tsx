import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";

import messages from "../../../messages/pl.json";
import type { PanelAccess } from "#lib/panel-navigation";
import { SidebarProvider } from "@saas-core/ui/components/sidebar";
import { AppSidebar } from "./app-sidebar";

// Core's menu alone: a product repository fills this slot with its own
// entries and messages, which this test neither knows nor needs.
vi.mock("../../product", () => ({ product: {} }));

vi.mock("#i18n/navigation", () => ({
  usePathname: () => "/panel",
  // The organization switcher inside the sidebar refreshes the shell.
  useRouter: () => ({ refresh: vi.fn() }),
  Link: ({
    children,
    ...props
  }: React.ComponentProps<"a"> & { children: React.ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));

const CORE_ONLY = ["core.health", "core.identity", "core.organizations"];
const BUSINESS = [
  ...CORE_ONLY,
  "shared.billing",
  "shared.sites",
  "shared.media",
  "shared.notifications",
  "shared.booking",
  "shared.seo",
];
const HOOFCARE = [...BUSINESS, "shared.farms", "vertical.hoofcare"];
/** The permissions of HoofCare's `trimmer` role, as its profile declares them. */
const TRIMMER = [
  "booking.appointment.read",
  "farms.manage",
  "farms.read",
  "hoofcare.herd.manage",
  "hoofcare.herd.read",
  "media.manage",
  "media.read",
  "notifications.preferences",
  "organization.read",
];

function renderSidebar(access: Partial<PanelAccess>) {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <SidebarProvider>
        <AppSidebar
          access={{
            modules: CORE_ONLY,
            permissions: null,
            isOwner: true,
            limited: false,
            ...access,
          }}
          attention={null}
          organizations={[]}
          roleLabel="Właściciel"
        />
      </SidebarProvider>
    </NextIntlClientProvider>,
  );
}

const hrefs = () =>
  screen
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"))
    .filter((href): href is string => href !== null);

afterEach(cleanup);

/**
 * The backend refuses to answer for a module a deployment does not have, and
 * for a permission the role lacks; the menu stops offering either for the
 * same reason, so a trimmer is not led to a page that answers 403.
 */
describe("menu panelu", () => {
  it("nie oferuje modułu, którego deployment nie ma", () => {
    renderSidebar({ modules: CORE_ONLY });

    const links = hrefs();
    expect(links).toEqual(["/panel", "/panel/team", "/panel/settings/company"]);
  });

  it("dzieli menu na Pracę i Firmę", () => {
    renderSidebar({ modules: BUSINESS });

    expect(screen.getByRole("navigation", { name: "Praca" })).not.toBeNull();
    expect(screen.getByRole("navigation", { name: "Firma" })).not.toBeNull();
    expect(hrefs()).toEqual([
      "/panel",
      "/panel/calendar",
      "/panel/team",
      "/panel/sites",
      "/panel/notifications",
      "/panel/settings/billing",
      "/panel/settings/company",
    ]);
  });

  it("korektor widzi pracę, bez zespołu, strony, wiadomości i abonamentu", () => {
    renderSidebar({
      modules: HOOFCARE,
      permissions: TRIMMER,
      isOwner: false,
      limited: true,
      organizationType: "trimming_company",
    });

    expect(hrefs()).toEqual([
      "/panel",
      "/panel/calendar",
      "/panel/farms",
      "/panel/animals",
      "/panel/settings/account",
    ]);
  });

  it("administrator bez własności trafia z Abonamentu do kredytów", () => {
    renderSidebar({ modules: BUSINESS, isOwner: false });

    expect(hrefs()).toContain("/panel/settings/credits");
    expect(hrefs()).not.toContain("/panel/settings/billing");
  });
});
