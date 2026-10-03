import type { ReactNode } from "react";
import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type { SettingsSchema } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import {
  SettingsSearch,
  searchSettings,
  settingsIndex,
} from "./settings-search";

const { getSettingsSchema } = vi.hoisted(() => ({
  getSettingsSchema: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({
  Link: ({
    children,
    href,
    onClick,
  }: {
    children: ReactNode;
    href: string;
    onClick?: () => void;
  }) => (
    <a href={href} onClick={onClick}>
      {children}
    </a>
  ),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  getSettingsSchema,
}));

const KEY = {
  minimum: null,
  maximum: null,
  unit: null,
  values: null,
  help: null,
  description: "",
  scopes: ["organization"],
  depends_on: null,
  strategy: "override" as const,
};

const SCHEMA = {
  areas: [
    {
      key: "company",
      title: { pl: "Dane firmy", en: "Company details" },
      description: { pl: "Waluta firmy.", en: "The company's currency." },
      page: "/panel/settings/company",
    },
    {
      key: "security",
      title: { pl: "Bezpieczeństwo", en: "Security" },
      description: { pl: "Logowanie.", en: "Sign-in." },
      page: null,
    },
  ],
  groups: [
    {
      key: "organization",
      module: "core.organizations",
      area: "company",
      title: { pl: "Firma", en: "Company" },
      description: { pl: "Podstawy.", en: "Basics." },
      permission: "organization.settings.manage",
      can_change: true,
      locked: "",
      api: "/api/v1/organizations/current/",
      step_up: false,
      keys: [
        {
          ...KEY,
          key: "organization.currency",
          type: "enum" as const,
          default: "PLN",
          label: { pl: "Waluta", en: "Currency" },
        },
      ],
    },
    {
      key: "organization.security",
      module: "core.organizations",
      area: "security",
      title: { pl: "Bezpieczeństwo", en: "Security" },
      description: { pl: "2FA.", en: "2FA." },
      permission: "organization.settings.manage",
      can_change: true,
      locked: "",
      api: null,
      step_up: false,
      keys: [
        {
          ...KEY,
          key: "organization.security.mfa_required",
          type: "enum" as const,
          default: "none",
          label: {
            pl: "Wymagaj weryfikacji dwuetapowej",
            en: "Require two-factor sign-in",
          },
          help: {
            pl: "Osoba bez 2FA nie wejdzie do firmy.",
            en: "A person without 2FA cannot enter the company.",
          },
        },
      ],
    },
  ],
} as unknown as SettingsSchema;

beforeEach(() => {
  vi.clearAllMocks();
  getSettingsSchema.mockResolvedValue(SCHEMA);
});

test("znajduje ustawienie po słowach w dowolnej kolejności, bez polskich liter, i prowadzi do pola", () => {
  const index = settingsIndex(SCHEMA, "pl");

  const found = searchSettings(index, "dwuetapowej wymagaj");
  expect(found.map((entry) => [entry.title, entry.href, entry.path])).toEqual([
    [
      "Wymagaj weryfikacji dwuetapowej",
      "/panel/settings/security#setting-organization.security-mfa_required",
      "Bezpieczeństwo › Bezpieczeństwo",
    ],
  ]);
  expect(searchSettings(index, "bezpieczenstwo").length).toBeGreaterThan(0);
  // A group its module stores itself leads to its page, not to a field.
  expect(searchSettings(index, "waluta")[0].href).toBe(
    "/panel/settings/company",
  );
  expect(searchSettings(index, "   ")).toEqual([]);
});

test("okno szukania pokazuje wyniki z łączem i nazywa brak wyników, PL i EN bez naruszeń axe", async () => {
  for (const [locale, text] of [
    ["pl", messages],
    ["en", englishMessages],
  ] as const) {
    const { unmount } = render(
      <NextIntlClientProvider locale={locale} messages={text}>
        <SettingsSearch />
      </NextIntlClientProvider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: text.CompanySettings.searchOpen }),
    );
    const field = await screen.findByLabelText(
      text.CompanySettings.searchLabel,
    );
    fireEvent.change(field, { target: { value: "2FA" } });
    const link = await screen.findByRole("link", {
      name: new RegExp(locale === "pl" ? "Wymagaj" : "Require"),
    });
    expect(link).toHaveAttribute(
      "href",
      "/panel/settings/security#setting-organization.security-mfa_required",
    );
    fireEvent.change(field, { target: { value: "nieistniejące" } });
    expect(
      await screen.findByText(
        text.CompanySettings.searchEmpty.replace("{query}", "nieistniejące"),
      ),
    ).toBeInTheDocument();
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
    unmount();
  }
});
