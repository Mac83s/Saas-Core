import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/pl.json";

/**
 * Two products, one panel component.
 *
 * The backend refuses to answer for a module a deployment does not have; the
 * menu has to stop offering it for the same reason, or `core-only` would show
 * a customer a plan page that answers 404. The composition is the only thing
 * deciding this, so it is the only thing this test changes.
 */
const { profile } = vi.hoisted(() => ({
  profile: {
    modules: [] as string[],
  },
}));

vi.mock("../../generated/deployment", () => ({
  deployment: {
    schemaVersion: 1,
    id: "test",
    product: { name: "Test", defaultLocale: "pl", supportedLocales: ["pl"] },
    get modules() {
      return profile.modules;
    },
    features: {},
    profileHash: "sha256:test",
  },
}));

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

async function renderSidebar(modules: string[]) {
  profile.modules = modules;
  // The composition is read at import time, so each profile needs its own
  // module graph — and everything sharing a React context with the component
  // has to come from that same graph, or the provider it finds is a different
  // one from the provider the test rendered.
  vi.resetModules();
  const { AppSidebar } = await import("./app-sidebar");
  const { SidebarProvider } = await import("@saas-core/ui/components/sidebar");
  const { NextIntlClientProvider } = await import("next-intl");
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <SidebarProvider>
        <AppSidebar
          userEmail="ktos@example.test"
          organizationName="Firma"
          organizations={[]}
          canManageBilling
        />
      </SidebarProvider>
    </NextIntlClientProvider>,
  );
}

const MODULE_LINKS = [
  "/panel/calendar",
  "/panel/sites",
  "/panel/seo",
  "/panel/notifications",
  "/panel/settings/billing",
];

const hrefs = () =>
  screen
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"))
    .filter((href): href is string => href !== null);

afterEach(cleanup);

describe("menu panelu", () => {
  it("nie oferuje modułu, którego deployment nie ma", async () => {
    await renderSidebar(CORE_ONLY);

    const links = hrefs();
    expect(links).toContain("/panel");
    for (const link of MODULE_LINKS) {
      expect(links).not.toContain(link);
    }
  });

  it("oferuje je, gdy deployment je składa", async () => {
    await renderSidebar(BUSINESS);

    const links = hrefs();
    for (const link of MODULE_LINKS) {
      expect(links).toContain(link);
    }
  });
});
