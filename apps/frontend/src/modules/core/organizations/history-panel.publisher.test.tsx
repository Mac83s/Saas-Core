import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { HistoryEntry, HistoryPage } from "@saas-core/api-client";
import polishMessages from "../../../../messages/pl.json";
import { PanelAccessProvider } from "#components/panel/panel-access";
import type { PanelAccess } from "#lib/panel-navigation";
import { HistoryPanel } from "./history-panel";

/**
 * „Historia zmian” in the platform's own workspace (ADR-079 pkt 29): what
 * was done to a builder page is still told, but the row does not lead to a
 * screen its panel has not. A company's history links as before.
 */
const { api } = vi.hoisted(() => ({
  api: {
    readOrganizationHistory: vi.fn(),
    readCatalogDictionary: vi.fn(),
    getSettingsSchema: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const row = (action: string, label: string, href: string): HistoryEntry =>
  ({
    id: crypto.randomUUID(),
    occurred_at: "2026-10-07T20:11:00Z",
    action,
    actor: { name: "Wydawca", email: "wydawca@example.test" },
    channel: "panel",
    acting: null,
    target_type: "page",
    target_id: crypto.randomUUID(),
    target: { label, href, at: null },
    changes: {},
    changed_fields: [],
    details: {},
  }) as HistoryEntry;

const PUBLISHER: PanelAccess = {
  modules: ["core.organizations", "shared.sites"],
  permissions: null,
  isOwner: true,
  limited: false,
  organizationType: "business",
  publisher: true,
};

function view(wrap: (panel: ReactNode) => ReactNode = (panel) => panel) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      {wrap(<HistoryPanel />)}
    </NextIntlClientProvider>,
  );
}
const hrefs = (container: HTMLElement) =>
  [...container.querySelectorAll("a")].map((link) => link.getAttribute("href"));

beforeEach(() => {
  vi.clearAllMocks();
  api.readCatalogDictionary.mockRejectedValue(new Error("no catalogue"));
  api.getSettingsSchema.mockRejectedValue(new Error("no schema"));
  api.readOrganizationHistory.mockResolvedValue({
    total: 4,
    page: 1,
    page_size: 25,
    actions: [],
    items: [
      row("sites.page.created", "O serwisie", "/panel/sites/pages/page-one"),
      row("sites.site.published", "Serwis", "/panel/sites?site=site-one"),
      row("sites.domain.created", "serwis.test", "/panel/sites/address"),
      row("sites.entry.published", "Wpis", "/panel/sites/blog?site=site-one"),
    ],
  } as HistoryPage);
});

test("wydawca: wiersz o podstronie, witrynie i domenie mówi, czego dotyczył, i nigdzie nie prowadzi", async () => {
  const { container } = view((panel) => (
    <PanelAccessProvider access={PUBLISHER}>{panel}</PanelAccessProvider>
  ));

  // Told all the same — by name.
  for (const label of ["O serwisie", "Serwis", "serwis.test"])
    expect(await screen.findByText(new RegExp(`: ${label}$`))).toBeTruthy();
  // Only the entry's row leads somewhere: its screen is the publisher's.
  expect(hrefs(container)).toEqual(["/panel/sites/blog?site=site-one"]);
});

test("firma: każdy z tych wierszy prowadzi tam, gdzie prowadził", async () => {
  const { container } = view();

  await screen.findByRole("link", { name: "O serwisie" });
  expect(hrefs(container)).toEqual([
    "/panel/sites/pages/page-one",
    "/panel/sites?site=site-one",
    "/panel/sites/address",
    "/panel/sites/blog?site=site-one",
  ]);
});
