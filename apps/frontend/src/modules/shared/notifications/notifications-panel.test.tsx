import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { ApiProblemError } from "@saas-core/api-client";
import { NotificationsPanel } from "./notifications-panel";

const {
  listSites,
  listSiteInquiries,
  markSiteInquiryRead,
  getNotificationPreferences,
  getNotificationTemplates,
  previewNotificationTemplate,
  updateNotificationPreferences,
} = vi.hoisted(() => ({
  listSites: vi.fn(),
  listSiteInquiries: vi.fn(),
  markSiteInquiryRead: vi.fn(),
  getNotificationPreferences: vi.fn(),
  getNotificationTemplates: vi.fn(),
  previewNotificationTemplate: vi.fn(),
  updateNotificationPreferences: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  listSites,
  listSiteInquiries,
  markSiteInquiryRead,
  getNotificationPreferences,
  getNotificationTemplates,
  previewNotificationTemplate,
  updateNotificationPreferences,
}));

beforeEach(() => {
  vi.clearAllMocks();
  listSites.mockResolvedValue({ items: [], next_cursor: null });
  listSiteInquiries.mockResolvedValue({ items: [], next_cursor: null });
  getNotificationPreferences.mockResolvedValue({
    locale: "pl",
    marketing_enabled: false,
  });
  getNotificationTemplates.mockResolvedValue({
    items: [
      {
        key: "booking.reminder",
        version: 1,
        category: "required",
        locales: ["en", "pl"],
        context_fields: ["organization_name", "starts_at"],
      },
      {
        key: "product.update",
        version: 1,
        category: "marketing",
        locales: ["en", "pl"],
        context_fields: ["display_name", "message"],
      },
    ],
  });
  previewNotificationTemplate.mockImplementation(
    async ({ locale }: { locale: string }) => ({
      subject: `Temat z API (${locale})`,
      html_body: "<p>Treść dla {organization_name}</p>",
    }),
  );
  updateNotificationPreferences.mockImplementation(async (value) => value);
});

afterEach(cleanup);

function renderPanel(locale: "pl" | "en" = "pl", canManageBilling = true) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <NotificationsPanel canManageBilling={canManageBilling} />
    </NextIntlClientProvider>,
  );
}

test.each([
  ["pl", "Przypomnienie o rezerwacji", "Nazwa firmy", "Twoje powiadomienia"],
  ["en", "Booking reminder", "Business name", "Your notifications"],
] as const)(
  "pokazuje szablony z nazwami, zmiennymi i podglądem w locale %s",
  async (locale, templateName, variable, preferences) => {
    const rendered = renderPanel(locale);

    expect(
      await screen.findByRole("heading", { name: templateName }),
    ).not.toBeNull();
    expect(screen.getByText("{organization_name}")).not.toBeNull();
    expect(screen.getByText(variable)).not.toBeNull();
    expect(await screen.findByText(`Temat z API (${locale})`)).not.toBeNull();
    expect(screen.getByRole("heading", { name: preferences })).not.toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

test("podgląd podstawia zmienne szablonu i zmienia język bez wysyłania", async () => {
  renderPanel();

  expect(await screen.findByText("Temat z API (pl)")).not.toBeNull();
  // Each variable stands in for itself, so the preview shows where it lands.
  expect(previewNotificationTemplate).toHaveBeenLastCalledWith({
    key: "booking.reminder",
    version: 1,
    locale: "pl",
    context: {
      organization_name: "{organization_name}",
      starts_at: "{starts_at}",
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(await screen.findByText("Temat z API (en)")).not.toBeNull();

  // Another template keeps the language chosen for the preview.
  fireEvent.click(screen.getByRole("button", { name: /Nowości w usłudze/ }));
  await waitFor(() =>
    expect(previewNotificationTemplate).toHaveBeenLastCalledWith({
      key: "product.update",
      version: 1,
      locale: "en",
      context: { display_name: "{display_name}", message: "{message}" },
    }),
  );
  expect(
    screen.getByRole("button", { name: /Nowości w usłudze/ }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(previewNotificationTemplate).toHaveBeenCalledTimes(3);
});

test("zapisuje zgodę marketingową we własnych preferencjach", async () => {
  renderPanel();

  const consent = await screen.findByRole("checkbox", {
    name: /Wiadomości marketingowe/,
  });
  fireEvent.click(consent);
  fireEvent.click(screen.getByRole("button", { name: "Zapisz preferencje" }));

  await waitFor(() =>
    expect(updateNotificationPreferences).toHaveBeenCalledWith({
      locale: "pl",
      marketing_enabled: true,
    }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Preferencje zapisane.",
  );
});

test("bez wiadomości w planie właściciel dostaje drogę do planów", async () => {
  getNotificationTemplates.mockRejectedValue(problem("entitlement_required"));
  getNotificationPreferences.mockRejectedValue(problem("entitlement_required"));

  renderPanel();

  expect(
    await screen.findByText("Wiadomości nie są dostępne w Twoim planie"),
  ).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Porównaj plany" }).getAttribute("href"),
  ).toBe("/panel/settings/billing?feature=notifications.enabled");
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "Twoje powiadomienia" }),
    ).toBeNull(),
  );
});

test("bez wiadomości w planie pozostali dostają prośbę do właściciela", async () => {
  getNotificationTemplates.mockRejectedValue(problem("entitlement_required"));

  renderPanel("pl", false);

  expect(
    await screen.findByText("Poproś właściciela firmy o zmianę planu."),
  ).not.toBeNull();
  expect(screen.queryByRole("link", { name: "Porównaj plany" })).toBeNull();
});

test("po błędzie szablonów pozwala ponowić, a preferencje działają dalej", async () => {
  getNotificationTemplates.mockRejectedValueOnce(new Error("offline"));

  renderPanel();

  expect(
    await screen.findByText("Nie udało się pobrać szablonów wiadomości."),
  ).not.toBeNull();
  expect(
    await screen.findByRole("button", { name: "Zapisz preferencje" }),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(
    await screen.findByRole("heading", { name: "Przypomnienie o rezerwacji" }),
  ).not.toBeNull();
});

function problem(code: string) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Forbidden",
    status: 403,
    code,
    detail: "Plan organizacji nie pozwala na tę operację.",
    correlation_id: null,
  });
}

test.each(["pl", "en"] as const)(
  "dopuszcza samą skrzynkę %s bez zapytań do powiadomień automatycznych",
  async (locale) => {
    const result = render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? polishMessages : englishMessages}
      >
        <NotificationsPanel
          canManageNotifications={false}
          canReadSiteInquiries
        />
      </NextIntlClientProvider>,
    );
    expect(
      await screen.findByText(
        locale === "pl"
          ? /Nie masz jeszcze witryny/
          : /You do not have a website yet/,
      ),
    ).not.toBeNull();
    expect(getNotificationTemplates).not.toHaveBeenCalled();
    expect(getNotificationPreferences).not.toHaveBeenCalled();
    expect((await axe.run(result.container)).violations).toHaveLength(0);
  },
);

test("oddziela skrzynkę i automatyczne powiadomienia dostępnymi zakładkami", async () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <NotificationsPanel canReadSiteInquiries canManageNotifications />
    </NextIntlClientProvider>,
  );
  expect(
    await screen.findByText(/You do not have a website yet/),
  ).not.toBeNull();
  expect(
    screen.getByRole("tab", { name: "Website inquiries" }),
  ).toHaveAttribute("aria-selected", "true");
  expect(getNotificationTemplates).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "Automatic notifications" }));
  expect(
    await screen.findByRole("heading", { name: "Booking reminder" }),
  ).not.toBeNull();
  expect(
    screen.getByRole("tab", { name: "Automatic notifications" }),
  ).toHaveAttribute("aria-selected", "true");
});

test("brak obu uprawnień nie wywołuje endpointów ani nie pokazuje treści", () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <NotificationsPanel
        canManageNotifications={false}
        canReadSiteInquiries={false}
      />
    </NextIntlClientProvider>,
  );
  expect(listSites).not.toHaveBeenCalled();
  expect(listSiteInquiries).not.toHaveBeenCalled();
  expect(getNotificationTemplates).not.toHaveBeenCalled();
  expect(getNotificationPreferences).not.toHaveBeenCalled();
  expect(screen.queryByRole("heading")).toBeNull();
});
