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
import { ApiProblemError } from "@saas-core/api-client";
import pl from "../../../../messages/pl.json";
import en from "../../../../messages/en.json";
import { SeoGscPanel } from "./gsc-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
const api = vi.hoisted(() => ({
  listSites: vi.fn(),
  getSeoGscProperties: vi.fn(),
  getSeoGscConnection: vi.fn(),
  listSeoGscGrants: vi.fn(),
  listSeoGscSyncs: vi.fn(),
  prepareSeoGsc: vi.fn(),
  createSeoGscGrant: vi.fn(),
  readSeoGscGrant: vi.fn(),
  revokeSeoGsc: vi.fn(),
  disconnectSeoGsc: vi.fn(),
  readSeoGscMetrics: vi.fn(),
  syncSeoGsc: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
const siteId = "019ff20d-d000-7000-8000-000000000002";
const propertyId = "019ff20d-d000-7000-8000-000000000003";
const grant = {
  id: "grant-1",
  site_id: siteId,
  property_id: propertyId,
  site_url: "sc-domain:example.test",
  connected: true,
  expires_at: "2026-10-06T12:00:00Z",
  revoked_at: null,
  scopes: ["read", "sync"],
  latest_sync: {
    id: "sync-1",
    client_reference: "ref-1",
    status: "completed",
    rows_received: 1,
    is_truncated: false,
  },
};
beforeEach(() => {
  vi.resetAllMocks();
  api.listSites.mockResolvedValue({
    items: [
      { id: siteId, name: "Example" },
      { id: "other", name: "Other" },
    ],
    next_cursor: null,
  });
  api.getSeoGscProperties.mockResolvedValue({
    connected: true,
    connection_id: "connection-1",
    properties: [
      {
        id: propertyId,
        site_url: "sc-domain:example.test",
        permission_level: "siteOwner",
      },
    ],
  });
  api.listSeoGscGrants.mockResolvedValue({
    items: [
      {
        id: grant.id,
        property_id: propertyId,
        expires_at: grant.expires_at,
        outcome_known: true,
      },
    ],
    next_cursor: null,
  });
  api.listSeoGscSyncs.mockResolvedValue({ items: [] });
  api.readSeoGscGrant.mockResolvedValue(grant);
  api.createSeoGscGrant.mockResolvedValue(grant);
  api.revokeSeoGsc.mockResolvedValue({
    ...grant,
    connected: false,
    revoked_at: "2026-09-06T12:00:00Z",
    latest_sync: null,
  });
  api.disconnectSeoGsc.mockResolvedValue({ disconnected: true });
  api.readSeoGscMetrics.mockResolvedValue({
    count: 1,
    next_page: null,
    results: [
      {
        date: "2026-09-01",
        query: "private query",
        page: "https://example.test/",
        clicks: 2,
        impressions: 4,
        position: 2,
      },
    ],
  });
});
afterEach(cleanup);
function view(locale: "pl" | "en" = "en") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? pl : en}
    >
      <main>
        <SeoGscPanel />
      </main>
    </NextIntlClientProvider>,
  );
}
async function choose(locale: "pl" | "en" = "en") {
  await screen.findByRole("option", { name: "Example" });
  fireEvent.change(
    screen.getByLabelText(locale === "pl" ? "Strona internetowa" : "Website"),
    { target: { value: siteId } },
  );
  await screen.findByText(
    locale === "pl"
      ? "Konto Google jest połączone."
      : "A Google account is connected.",
  );
}
test.each(["pl", "en"] as const)(
  "Google panel is accessible in %s and never grants automatically",
  async (locale) => {
    const { container } = view(locale);
    await choose(locale);
    expect(api.createSeoGscGrant).not.toHaveBeenCalled();
    expect((await axe.run(container)).violations).toEqual([]);
  },
);
test("disconnect requires explicit organization confirmation and exact current connection", async () => {
  view();
  await choose();
  expect(
    screen.getByRole("button", { name: "Disconnect the organization" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "I confirm disconnecting Google for the entire organization.",
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Disconnect the organization" }),
  );
  await waitFor(() =>
    expect(api.disconnectSeoGsc).toHaveBeenCalledWith({
      site_id: siteId,
      connection_id: "connection-1",
      confirm_workspace_disconnect: true,
    }),
  );
});
test("revoke clears private metrics and retained history remains", async () => {
  view();
  await choose();
  fireEvent.click(screen.getByRole("button", { name: "View current access" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load current search data" }),
  );
  await screen.findByText("private query");
  fireEvent.click(
    screen.getByRole("button", { name: "Revoke access for this website" }),
  );
  await waitFor(() =>
    expect(screen.queryByText("private query")).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: "View current access" }),
  ).toBeInTheDocument();
});
test("unknown grant retry preserves exact body including expiry and idempotency", async () => {
  api.createSeoGscGrant.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Unknown",
      status: 503,
      code: "test",
      detail: null,
      correlation_id: null,
    }),
  );
  view();
  await choose();
  fireEvent.change(screen.getByLabelText("Google property"), {
    target: { value: propertyId },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Grant access for 30 days" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry the saved operation" }),
  );
  await waitFor(() => expect(api.createSeoGscGrant).toHaveBeenCalledTimes(2));
  expect(api.createSeoGscGrant.mock.calls[1][0]).toEqual(
    api.createSeoGscGrant.mock.calls[0][0],
  );
});
test("a reader sees grant history even when connection management is forbidden", async () => {
  const denied = new ApiProblemError({
    type: "about:blank",
    title: "Denied",
    status: 403,
    code: "test",
    detail: null,
    correlation_id: null,
  });
  api.getSeoGscProperties.mockRejectedValue(denied);
  api.getSeoGscConnection.mockRejectedValue(denied);
  view();
  await screen.findByRole("option", { name: "Example" });
  fireEvent.change(screen.getByLabelText("Website"), {
    target: { value: siteId },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "View current access" }),
  );
  expect(await screen.findByText("Access is active.")).toBeInTheDocument();
});
test("switching sites removes already displayed private metrics", async () => {
  view();
  await choose();
  fireEvent.click(screen.getByRole("button", { name: "View current access" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load current search data" }),
  );
  await screen.findByText("private query");
  fireEvent.change(screen.getByLabelText("Website"), {
    target: { value: "other" },
  });
  expect(screen.queryByText("private query")).not.toBeInTheDocument();
});
