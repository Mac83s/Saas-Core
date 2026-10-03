import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiProblemError } from "@saas-core/api-client";
import pl from "../../../../messages/pl.json";
import en from "../../../../messages/en.json";
import { SeoGscPanel } from "./gsc-panel";

vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/seo/search-console",
}));
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
        created_at: "2026-09-06T12:00:00Z",
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
test("one website needs no choosing: its connection and the steps show at once (UX-046, 47a)", async () => {
  api.listSites.mockResolvedValue({
    items: [{ id: siteId, name: "Example" }],
    next_cursor: null,
  });
  view("pl");
  expect(
    await screen.findByText("Konto Google jest połączone."),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Strona internetowa")).not.toBeInTheDocument();
  expect(api.getSeoGscProperties).toHaveBeenCalledWith(siteId);
  expect(
    screen.getByText(/Połącz konto Google, na którym strona/),
  ).toBeInTheDocument();
  // Audits and Search Console are tabs of one entry.
  const tabs = screen.getByRole("navigation", { name: "Widoczność w Google" });
  expect(
    within(tabs)
      .getByRole("link", { name: "Search Console" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

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
test("access history is a table and the next page joins it", async () => {
  api.listSeoGscGrants
    .mockResolvedValueOnce({
      items: [
        {
          id: grant.id,
          property_id: propertyId,
          expires_at: grant.expires_at,
          created_at: "2026-09-06T12:00:00Z",
          outcome_known: true,
        },
      ],
      next_cursor: "cursor-2",
    })
    .mockResolvedValueOnce({
      items: [
        {
          id: "grant-0",
          property_id: propertyId,
          expires_at: "2026-09-01T12:00:00Z",
          created_at: "2026-08-02T12:00:00Z",
          outcome_known: false,
        },
      ],
      next_cursor: null,
    });
  view();
  await choose();
  const history = screen.getByRole("table", { name: "Access history" });
  const rows = within(history).getAllByRole("row");
  expect(rows).toHaveLength(2);
  expect(
    within(rows[1]).getByText("sc-domain:example.test"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show next page" }));
  await waitFor(() =>
    expect(within(history).getAllByRole("row")).toHaveLength(3),
  );
  expect(api.listSeoGscGrants).toHaveBeenLastCalledWith(siteId, "cursor-2");
  // A grant whose outcome is unknown offers the retry instead of opening.
  expect(
    within(within(history).getAllByRole("row")[2]).getByRole("button", {
      name: "Retry the saved operation",
    }),
  ).toBeInTheDocument();
});
test("a saved sync range is listed and retried with the same receipt", async () => {
  api.listSeoGscSyncs.mockResolvedValue({
    items: [
      {
        client_reference: "ref-1",
        start_date: "2026-08-01",
        end_date: "2026-08-30",
        remote_id: "sync-1",
      },
    ],
  });
  api.syncSeoGsc.mockResolvedValue({ ...grant.latest_sync, id: "sync-2" });
  view();
  await choose();
  fireEvent.click(screen.getByRole("button", { name: "View current access" }));
  const syncs = await screen.findByRole("table", {
    name: "Saved synchronization ranges",
  });
  expect(
    within(syncs).getByText("2026-08-01 – 2026-08-30"),
  ).toBeInTheDocument();
  fireEvent.click(
    within(syncs).getByRole("button", { name: "Retry the saved operation" }),
  );
  await waitFor(() =>
    expect(api.syncSeoGsc).toHaveBeenCalledWith("grant-1", {
      client_reference: "ref-1",
      start_date: "2026-08-01",
      end_date: "2026-08-30",
    }),
  );
});
test("search data pages through the API, one page at a time", async () => {
  const metric = (query: string) => ({
    date: "2026-09-01",
    query,
    page: "https://example.test/",
    clicks: 2,
    impressions: 4,
    position: 2,
  });
  api.readSeoGscMetrics
    .mockResolvedValueOnce({
      count: 30,
      next_page: 2,
      results: [metric("private query")],
    })
    .mockResolvedValueOnce({
      count: 30,
      next_page: null,
      results: [metric("second page query")],
    });
  const { container } = view();
  await choose();
  fireEvent.click(screen.getByRole("button", { name: "View current access" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Load current search data" }),
  );
  const table = await screen.findByRole("table", {
    name: "Search data from this synchronization",
  });
  expect(within(table).getByText("private query")).toBeInTheDocument();
  expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(await screen.findByText("second page query")).toBeInTheDocument();
  expect(api.readSeoGscMetrics).toHaveBeenLastCalledWith(
    "grant-1",
    "sync-1",
    2,
  );
  expect(screen.queryByText("private query")).not.toBeInTheDocument();
  expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  expect((await axe.run(container)).violations).toEqual([]);
});
