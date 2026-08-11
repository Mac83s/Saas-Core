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

import polishMessages from "../../../../messages/pl.json";
import { DomainPanel } from "./domain-panel";

const { createSiteDomain, listSiteDomains, mutateSiteDomain } = vi.hoisted(
  () => ({
    createSiteDomain: vi.fn(),
    listSiteDomains: vi.fn(),
    mutateSiteDomain: vi.fn(),
  }),
);

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createSiteDomain,
  listSiteDomains,
  mutateSiteDomain,
}));

const siteId = "019ff20d-a000-7000-8000-000000000001";
const platformDomain = {
  id: "019ff20d-a000-7000-8000-000000000010",
  site_id: siteId,
  hostname: "clinic-019ff20da000.core.localhost",
  kind: "platform",
  status: "verified",
  tls_status: "eligible",
  is_canonical: true,
  verification_name: "",
  verification_token: "",
  dns_cname_target: "core.localhost",
  dns_expected_ipv4: [],
  dns_expected_ipv6: [],
  dns_error_code: "",
  last_checked_at: "2026-08-12T08:00:00Z",
  last_verified_at: "2026-08-12T08:00:00Z",
  next_check_at: null,
  tls_last_requested_at: null,
  released_at: null,
  quarantine_until: null,
  created_at: "2026-08-12T08:00:00Z",
};
const customDomain = {
  ...platformDomain,
  id: "019ff20d-a000-7000-8000-000000000011",
  hostname: "www.example.test",
  kind: "custom",
  status: "pending",
  tls_status: "pending",
  is_canonical: false,
  verification_name: "_saas-core.www.example.test",
  verification_token: "saas-core-domain-verification=token",
  dns_cname_target: "sites.core.localhost",
  last_checked_at: null,
  last_verified_at: null,
  next_check_at: "2026-08-12T08:01:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  listSiteDomains.mockResolvedValue({ items: [platformDomain, customDomain] });
  createSiteDomain.mockResolvedValue(customDomain);
  mutateSiteDomain.mockResolvedValue({ ...customDomain, status: "verified" });
});

afterEach(cleanup);

function renderPanel() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <DomainPanel siteId={siteId} />
    </NextIntlClientProvider>,
  );
}

test("pokazuje status, instrukcję DNS i uruchamia kontrolę", async () => {
  renderPanel();

  expect(await screen.findByText("www.example.test")).not.toBeNull();
  expect(screen.getByText(/_saas-core\.www\.example\.test/)).not.toBeNull();
  expect(screen.getByText("TLS: oczekuje")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź DNS" }));

  await waitFor(() => expect(mutateSiteDomain).toHaveBeenCalledOnce());
  expect(mutateSiteDomain.mock.calls[0]?.[0]).toBe(customDomain.id);
  expect(mutateSiteDomain.mock.calls[0]?.[1]).toEqual({ action: "verify" });
});

test("dodaje własną domenę i przechodzi axe", async () => {
  const rendered = renderPanel();
  const input = await screen.findByLabelText("Własna domena");
  fireEvent.change(input, { target: { value: "new.example.test" } });
  fireEvent.click(screen.getByRole("button", { name: "Dodaj domenę" }));

  await waitFor(() => expect(createSiteDomain).toHaveBeenCalledOnce());
  expect(createSiteDomain.mock.calls[0]?.[0]).toBe(siteId);
  expect(createSiteDomain.mock.calls[0]?.[1]).toEqual({
    hostname: "new.example.test",
  });
  const result = await axe.run(rendered.container);
  expect(result.violations).toHaveLength(0);
});
