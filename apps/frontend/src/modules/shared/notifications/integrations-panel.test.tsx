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

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import type {
  IntegrationApiKey,
  IntegrationWebhook,
} from "@saas-core/api-client";
import { IntegrationsPanel } from "./integrations-panel";

const api = vi.hoisted(() => ({
  createIntegrationApiKey: vi.fn(),
  createIntegrationWebhook: vi.fn(),
  listIntegrationApiKeys: vi.fn(),
  listIntegrationWebhooks: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const key: IntegrationApiKey = {
  id: "019ff20d-a000-7000-8000-000000000031",
  name: "Księgowość",
  prefix: "sk_live_ab12",
  scopes: ["notifications:read"],
  revoked_at: null,
  expires_at: null,
  created_at: "2026-09-01T10:00:00Z",
};
const revoked: IntegrationApiKey = {
  ...key,
  id: "019ff20d-a000-7000-8000-000000000032",
  name: "Stary CRM",
  prefix: "sk_live_cd34",
  revoked_at: "2026-09-10T10:00:00Z",
};
const webhook: IntegrationWebhook = {
  id: "019ff20d-a000-7000-8000-000000000041",
  name: "Publikacja strony",
  url: "https://example.com/hooks/site",
  events: ["sites.site.published"],
  active: true,
  secret_hint: "9f3a",
  created_at: "2026-09-02T10:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listIntegrationApiKeys.mockResolvedValue([key, revoked]);
  api.listIntegrationWebhooks.mockResolvedValue([webhook]);
});

afterEach(cleanup);

function renderPanel(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <IntegrationsPanel />
    </NextIntlClientProvider>,
  );
}

async function expectAccessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

test.each([
  ["pl", "Klucze API", "Webhooki wychodzące", "wycofany"],
  ["en", "API keys", "Outbound webhooks", "revoked"],
] as const)(
  "klucze i webhooki są listami w locale %s",
  async (locale, keysTitle, webhooksTitle, revokedLabel) => {
    const { container } = renderPanel(locale);

    const keys = await screen.findByRole("table", { name: keysTitle });
    const keyRows = within(keys).getAllByRole("row");
    expect(keyRows).toHaveLength(3);
    expect(within(keyRows[1]!).getByText("Księgowość")).toBeInTheDocument();
    expect(within(keyRows[1]!).getByText("sk_live_ab12…")).toBeInTheDocument();
    expect(within(keyRows[2]!).getByText(revokedLabel)).toBeInTheDocument();

    const hooks = screen.getByRole("table", { name: webhooksTitle });
    const hookRows = within(hooks).getAllByRole("row");
    expect(hookRows).toHaveLength(2);
    expect(
      within(hookRows[1]!).getByText("https://example.com/hooks/site"),
    ).toBeInTheDocument();
    expect(within(hookRows[1]!).getByText("…9f3a")).toBeInTheDocument();

    await expectAccessible(container);
  },
);

test("nowy klucz powstaje w oknie, a sekret widać tylko raz nad listą", async () => {
  const created: IntegrationApiKey = {
    ...key,
    id: "019ff20d-a000-7000-8000-000000000033",
    name: "Magazyn",
    prefix: "sk_live_ef56",
    secret: "sk_live_ef56_full_secret",
  };
  api.createIntegrationApiKey.mockResolvedValue(created);
  renderPanel();
  await screen.findByRole("table", { name: "Klucze API" });

  const trigger = screen.getByRole("button", { name: "Nowy klucz API" });
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Nowy klucz API" });
  api.listIntegrationApiKeys.mockResolvedValue([key, revoked, created]);
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Magazyn" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Utwórz" }));

  await waitFor(() =>
    expect(api.createIntegrationApiKey).toHaveBeenCalledWith({
      name: "Magazyn",
      scopes: ["notifications:read"],
    }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "sk_live_ef56_full_secret",
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(api.listIntegrationApiKeys).toHaveBeenCalledTimes(2);
  expect(
    await within(screen.getByRole("table", { name: "Klucze API" })).findByText(
      "Magazyn",
    ),
  ).toBeInTheDocument();
  // The list shows the prefix only; the full secret is in the notice alone.
  expect(screen.getAllByText(/sk_live_ef56_full_secret/)).toHaveLength(1);
});

test("nieudane utworzenie webhooka zostaje w oknie z komunikatem", async () => {
  api.createIntegrationWebhook.mockRejectedValue(new Error("offline"));
  renderPanel();
  await screen.findByRole("table", { name: "Webhooki wychodzące" });

  fireEvent.click(screen.getByRole("button", { name: "Nowy webhook" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowy webhook" });
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "CRM" },
  });
  fireEvent.change(within(dialog).getByLabelText("URL HTTPS"), {
    target: { value: "https://crm.example.com/hook" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Utwórz" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Nie udało się utworzyć integracji.",
  );
  expect(api.createIntegrationWebhook).toHaveBeenCalledWith({
    name: "CRM",
    url: "https://crm.example.com/hook",
    events: ["sites.site.published"],
  });
  expect(screen.queryByRole("status")).toBeNull();
});

test("pusta lista mówi, że nie ma jeszcze kluczy ani webhooków", async () => {
  api.listIntegrationApiKeys.mockResolvedValue([]);
  api.listIntegrationWebhooks.mockResolvedValue([]);
  renderPanel("en");

  expect(await screen.findByText("There are no API keys yet.")).toBeVisible();
  expect(screen.getByText("There are no webhooks yet.")).toBeVisible();
});

test("błąd odczytu pokazuje komunikat zamiast pustych list", async () => {
  api.listIntegrationApiKeys.mockRejectedValue(new Error("offline"));
  renderPanel();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się pobrać integracji.",
  );
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText("Nie ma jeszcze kluczy API.")).toBeNull();
});
