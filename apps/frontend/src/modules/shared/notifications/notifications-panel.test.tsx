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
import { NotificationsPanel } from "./notifications-panel";

const {
  getNotificationPreferences,
  getNotificationTemplates,
  previewNotificationTemplate,
  updateNotificationPreferences,
} = vi.hoisted(() => ({
  getNotificationPreferences: vi.fn(),
  getNotificationTemplates: vi.fn(),
  previewNotificationTemplate: vi.fn(),
  updateNotificationPreferences: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getNotificationPreferences,
  getNotificationTemplates,
  previewNotificationTemplate,
  updateNotificationPreferences,
}));

beforeEach(() => {
  vi.clearAllMocks();
  getNotificationPreferences.mockResolvedValue({
    locale: "pl",
    marketing_enabled: false,
  });
  getNotificationTemplates.mockResolvedValue({
    items: [
      {
        key: "system.activity",
        version: 1,
        category: "required",
        locales: ["en", "pl"],
        context_fields: ["display_name", "message"],
      },
    ],
  });
  previewNotificationTemplate.mockResolvedValue({
    subject: "Ważna informacja o koncie",
    html_body: "<p>Bezpieczny podgląd</p>",
  });
  updateNotificationPreferences.mockImplementation(async (value) => value);
});

afterEach(cleanup);

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "renders accessible preferences and templates in %s",
  async (locale, messages) => {
    const rendered = render(
      <NextIntlClientProvider locale={locale} messages={messages}>
        <NotificationsPanel />
      </NextIntlClientProvider>,
    );

    expect(await screen.findByText("system.activity v1")).not.toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

test("updates consent and previews without sending a message", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <NotificationsPanel />
    </NextIntlClientProvider>,
  );
  await screen.findByText("system.activity v1");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz preferencje" }));
  await waitFor(() =>
    expect(updateNotificationPreferences).toHaveBeenCalledWith({
      locale: "pl",
      marketing_enabled: true,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Podgląd" }));
  expect(await screen.findByText("Ważna informacja o koncie")).not.toBeNull();
  expect(previewNotificationTemplate).toHaveBeenCalledOnce();
});
