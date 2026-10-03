import type { ReactNode } from "react";
import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type PlatformSchema } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import { PlatformSettings } from "./platform-settings";

const {
  changePlatformSetting,
  confirmStepUp,
  getPlatformSettingHistory,
  getPlatformSettings,
  previewPlatformSetting,
} = vi.hoisted(() => ({
  changePlatformSetting: vi.fn(),
  confirmStepUp: vi.fn(),
  getPlatformSettingHistory: vi.fn(),
  getPlatformSettings: vi.fn(),
  previewPlatformSetting: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({
  Link: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  changePlatformSetting,
  confirmStepUp,
  getPlatformSettingHistory,
  getPlatformSettings,
  previewPlatformSetting,
}));

const KEY = {
  minimum: null,
  maximum: null,
  unit: null,
  values: null,
  help: null,
  description: "Probe.",
  depends_on: null,
  strategy: "override",
  max_length: null,
} as const;

function schema(level: number): PlatformSchema {
  return {
    operator_level: level,
    areas: [
      {
        key: "bookings",
        title: { pl: "Rezerwacje", en: "Bookings" },
        description: { pl: "Opis", en: "Description" },
      },
    ],
    groups: [
      {
        key: "booking.reminders",
        area: "bookings",
        title: { pl: "Przypomnienia o wizycie", en: "Visit reminders" },
        description: { pl: "Czy i kiedy.", en: "Whether and when." },
        keys: [
          {
            ...KEY,
            key: "booking.reminders.lead_hours",
            type: "int",
            minimum: 1,
            maximum: 168,
            default: 24,
            label: {
              pl: "Ile godzin przed wizytą",
              en: "Hours before the visit",
            },
            scopes: ["platform", "organization"],
            value: 24,
            source: "code",
            operator_level: 2,
            can_change: level >= 2,
            product_value: null,
          },
          {
            ...KEY,
            key: "booking.reminders.note",
            type: "text",
            default: "",
            label: { pl: "Notka", en: "Note" },
            scopes: ["platform"],
            value: "Stara",
            source: "platform",
            operator_level: 1,
            can_change: true,
            product_value: null,
          },
        ],
      },
    ],
  } as unknown as PlatformSchema;
}

function renderPage(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? messages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <PlatformSettings />
    </NextIntlClientProvider>,
  );
}

/** The page stands in the panel's `main`; a test renders it without one. */
async function noViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
      region: { enabled: false },
    },
  });
  expect(results.violations).toEqual([]);
}

beforeEach(() => {
  vi.clearAllMocks();
  getPlatformSettings.mockResolvedValue(schema(1));
});

test("operator poziomu 1 zmienia klucz poziomu 1 z powodem, po podglądzie skutku", async () => {
  previewPlatformSetting.mockResolvedValue({
    key: "booking.reminders.note",
    current: "Stara",
    proposed: "Nowa",
    companies_following: null,
    product_value: null,
  });
  changePlatformSetting.mockResolvedValue({
    key: "booking.reminders.note",
    value: "Nowa",
    source: "platform",
    operator_level: 1,
  });
  const { container } = renderPage();

  expect(
    await screen.findByText("Ile godzin przed wizytą"),
  ).toBeInTheDocument();
  expect(screen.getByText("Domyślne z kodu")).toBeInTheDocument();
  expect(screen.getByText("Poziom 2")).toBeInTheDocument();
  // A level-2 key is only seen by a level-1 operator.
  expect(
    screen.queryByRole("button", { name: "Zmień: Ile godzin przed wizytą" }),
  ).toBeNull();
  await noViolations(container);

  fireEvent.click(screen.getByRole("button", { name: "Zmień: Notka" }));
  const value = await screen.findByLabelText("Nowa wartość");
  fireEvent.change(value, { target: { value: "Nowa" } });
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź skutek" }));
  expect(
    await screen.findByText("Podaj powód: trafia do historii."),
  ).toBeInTheDocument();
  expect(previewPlatformSetting).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Powód zmiany"), {
    target: { value: "Nowy tekst" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź skutek" }));
  expect(
    await screen.findByText(
      "Tego klucza firmy nie ustawiają — zmiana działa na całej platformie.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Było: Stara → będzie: Nowa")).toBeInTheDocument();
  expect(changePlatformSetting).not.toHaveBeenCalled();
  await noViolations(document.body);

  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmianę" }));
  await waitFor(() =>
    expect(changePlatformSetting).toHaveBeenCalledWith(
      "booking.reminders.note",
      {
        value: "Nowa",
        reason: "Nowy tekst",
      },
    ),
  );
  await waitFor(() => expect(getPlatformSettings).toHaveBeenCalledTimes(2));
});

test("a level-2 key counts the companies it reaches and takes a fresh code", async () => {
  getPlatformSettings.mockResolvedValue(schema(2));
  previewPlatformSetting.mockResolvedValue({
    key: "booking.reminders.lead_hours",
    current: 24,
    proposed: 48,
    companies_following: 3,
    product_value: null,
  });
  changePlatformSetting
    .mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "Forbidden",
        status: 403,
        code: "step_up_required",
        detail: "Potwierdź.",
        correlation_id: null,
      }),
    )
    .mockResolvedValueOnce({
      key: "booking.reminders.lead_hours",
      value: 48,
      source: "platform",
      operator_level: 2,
    });
  confirmStepUp.mockResolvedValue(undefined);
  renderPage("en");

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Change: Hours before the visit",
    }),
  );
  fireEvent.change(await screen.findByLabelText("New value"), {
    target: { value: "48" },
  });
  fireEvent.change(screen.getByLabelText("Reason for the change"), {
    target: { value: "Pilot" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check the effect" }));
  expect(
    await screen.findByText(
      "Reaches 3 companies with no value of their own at once.",
    ),
  ).toBeInTheDocument();
  expect(previewPlatformSetting).toHaveBeenCalledWith(
    "booking.reminders.lead_hours",
    { value: 48, reason: "Pilot" },
  );

  fireEvent.click(screen.getByRole("button", { name: "Save the change" }));
  expect(
    await screen.findByText(
      "Changing a level-2 key takes a fresh code from your authenticator app.",
    ),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Code from the app"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

  await waitFor(() => expect(confirmStepUp).toHaveBeenCalledWith("123456"));
  await waitFor(() => expect(changePlatformSetting).toHaveBeenCalledTimes(2));
  await noViolations(document.body);
});

test("historia mówi kto i dlaczego, a wcześniejszą wartość da się ustawić ponownie", async () => {
  getPlatformSettingHistory.mockResolvedValue([
    {
      value: "Stara",
      operator: "operator@saas.test",
      reason: "Druga",
      created_at: "2026-10-03T10:00:00Z",
    },
    {
      value: "Pierwsza",
      operator: "operator@saas.test",
      reason: "Na start",
      created_at: "2026-10-02T10:00:00Z",
    },
    {
      value: null,
      operator: "admin@saas.test",
      reason: "Powrót",
      created_at: "2026-10-01T10:00:00Z",
    },
  ]);
  renderPage();

  fireEvent.click(
    await screen.findByRole("button", { name: "Historia: Notka" }),
  );
  expect(await screen.findByText("Na start")).toBeInTheDocument();
  expect(screen.getByText("Przywrócono domyślną")).toBeInTheDocument();
  // The newest entry is the value in force: nothing to set again.
  expect(
    screen.getAllByRole("button", { name: "Ustaw tę wartość ponownie" }),
  ).toHaveLength(1);
  await noViolations(document.body);

  fireEvent.click(
    screen.getByRole("button", { name: "Ustaw tę wartość ponownie" }),
  );
  const value = (await screen.findByLabelText(
    "Nowa wartość",
  )) as HTMLInputElement;
  expect(value.value).toBe("Pierwsza");
});

test("mówi, gdy domyślna produktu stoi nad wartością platformy", async () => {
  const shadowed = schema(2);
  shadowed.groups[0]!.keys[0]!.product_value = 36;
  getPlatformSettings.mockResolvedValue(shadowed);
  previewPlatformSetting.mockResolvedValue({
    key: "booking.reminders.lead_hours",
    current: 24,
    proposed: 48,
    companies_following: 0,
    product_value: 36,
  });
  renderPage();

  expect(
    await screen.findByText(
      "W tym wdrożeniu produkt ustawia: 36. Firma bez własnej wartości dostaje tę, nie wartość platformy.",
    ),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Zmień: Ile godzin przed wizytą" }),
  );
  fireEvent.change(await screen.findByLabelText("Nowa wartość"), {
    target: { value: "48" },
  });
  fireEvent.change(screen.getByLabelText("Powód zmiany"), {
    target: { value: "Pilot" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź skutek" }));
  expect(
    await screen.findByText(/ta zmiana nie dotrze do żadnej firmy/),
  ).toBeInTheDocument();
  await noViolations(document.body);
});
