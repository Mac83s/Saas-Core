import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { PanelAccessProvider } from "#components/panel/panel-access";
import { LanguagesPanel } from "./languages-panel";

/**
 * „Języki” in the platform's own workspace: the languages its content is
 * written in (ADR-079 pkt 29) — the screen a publisher switches a language on
 * at, said in those words. A company's screen is in `languages-panel.test.tsx`.
 */
const { api } = vi.hoisted(() => ({
  api: { getPublicLocales: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

beforeEach(() => {
  vi.clearAllMocks();
  api.getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en"],
    version: 4,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "en", native_name: "English", english_name: "English" },
      { code: "es", native_name: "Español", english_name: "Spanish" },
    ],
    // The platform's workspace is exempt from the plan's limit of languages.
    limit: { allowed: true, additional_max: null, reason: "" },
    protected: { pl: "site_default_not_removable" },
  });
});

test("wydawca: języki treści platformy, z językiem źródłowym treści i dodawaniem kolejnego", async () => {
  const { container } = render(
    <PanelAccessProvider
      access={{
        modules: ["core.organizations", "shared.sites"],
        permissions: null,
        isOwner: true,
        limited: false,
        publisher: true,
      }}
    >
      <NextIntlClientProvider
        locale="pl"
        messages={polishMessages}
        timeZone="Europe/Warsaw"
      >
        <LanguagesPanel />
      </NextIntlClientProvider>
    </PanelAccessProvider>,
  );

  expect(await screen.findByText("Język źródłowy treści")).toBeTruthy();
  expect(
    screen.getByText(
      /^Języki, w których platforma pisze i publikuje treści\. Kolejne dodajesz tutaj/,
    ),
  ).toBeTruthy();
  // The way to switch another language on stays where it was.
  expect(screen.getByRole("button", { name: "Dodaj język" })).toBeEnabled();
  expect(container).not.toHaveTextContent("Język źródłowy strony");
  expect(container).not.toHaveTextContent("wizytówka");
});

test("firma: słowa ekranu jak dotąd", async () => {
  const { container } = render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <LanguagesPanel />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("Język źródłowy strony")).toBeTruthy();
  expect(
    screen.getByText(/^Języki, w których firma mówi do klientów/),
  ).toBeTruthy();
  expect(container).not.toHaveTextContent("platforma pisze");
});
