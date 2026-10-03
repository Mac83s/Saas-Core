import type { ReactNode } from "react";
import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type SettingsGroupSchema,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import { SettingsGroupForm } from "./settings-group-form";

const {
  confirmStepUp,
  getSettingsGroup,
  previewSettingsGroup,
  updateSettingsGroup,
} = vi.hoisted(() => ({
  confirmStepUp: vi.fn(),
  getSettingsGroup: vi.fn(),
  previewSettingsGroup: vi.fn(),
  updateSettingsGroup: vi.fn(),
}));

vi.mock("#i18n/navigation", () => ({
  Link: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  confirmStepUp,
  getSettingsGroup,
  previewSettingsGroup,
  updateSettingsGroup,
}));

const GROUP: SettingsGroupSchema = {
  key: "booking.reminders",
  module: "shared.booking",
  area: "bookings",
  title: { pl: "Przypomnienia o wizycie", en: "Visit reminders" },
  description: { pl: "Czy i kiedy.", en: "Whether and when." },
  permission: "organization.settings.manage",
  can_change: true,
  locked: "",
  api: null,
  step_up: false,
  keys: [
    {
      key: "booking.reminders.enabled",
      type: "bool",
      minimum: null,
      maximum: null,
      unit: null,
      values: null,
      default: true,
      label: { pl: "Wysyłaj przypomnienia", en: "Send reminders" },
      help: null,
      description: "Whether.",
      scopes: ["organization"],
      depends_on: null,
      strategy: "override",
    },
    {
      key: "booking.reminders.lead_hours",
      type: "int",
      minimum: 1,
      maximum: 168,
      unit: "hour",
      values: null,
      default: 24,
      label: { pl: "Ile godzin przed wizytą", en: "Hours before the visit" },
      help: null,
      description: "When.",
      scopes: ["platform", "organization"],
      depends_on: "booking.reminders.enabled",
      strategy: "override",
    },
  ],
};

const STATE = {
  group: "booking.reminders",
  version: "v1",
  values: { enabled: true, lead_hours: 24 },
  sources: { enabled: "code", lead_hours: "platform" },
  can_change: true,
  locked: "",
};

function renderForm(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? messages : englishMessages}
    >
      <SettingsGroupForm group={GROUP} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getSettingsGroup.mockResolvedValue(STATE);
});

test("pokazuje źródło wartości, a zmiana z dodatkowym skutkiem czeka na potwierdzenie", async () => {
  previewSettingsGroup.mockResolvedValue({
    version: "v1",
    values: { enabled: true, lead_hours: 48 },
    changes: { lead_hours: { from: 24, to: 48 } },
    effects: [
      {
        kind: "rearmed",
        resource: "booking.appointment",
        resource_id: "",
        summary: { pl: "Przeliczy przypomnienia 3 wizyt.", en: "Re-plans 3." },
      },
    ],
  });
  updateSettingsGroup.mockResolvedValue({
    ...STATE,
    version: "v2",
    values: { enabled: true, lead_hours: 48 },
    sources: { enabled: "code", lead_hours: "organization" },
  });
  const { container } = renderForm();

  const hours = (await screen.findByLabelText(
    "Ile godzin przed wizytą",
  )) as HTMLInputElement;
  await waitFor(() => expect(hours.value).toBe("24"));
  expect(screen.getByText("Domyślne platformy")).toBeInTheDocument();
  fireEvent.change(hours, { target: { value: "48" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

  expect(
    await screen.findByText("Przeliczy przypomnienia 3 wizyt."),
  ).toBeInTheDocument();
  expect(previewSettingsGroup).toHaveBeenCalledWith("booking.reminders", {
    expected_version: "v1",
    reset: [],
    lead_hours: 48,
  });
  expect(updateSettingsGroup).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

  await waitFor(() =>
    expect(updateSettingsGroup).toHaveBeenCalledWith(
      "booking.reminders",
      { expected_version: "v1", reset: [], lead_hours: 48 },
      expect.any(String),
    ),
  );
  expect(await screen.findByText("Zapisano ustawienia.")).toBeInTheDocument();
  expect(screen.getByText("Ustawione dla firmy")).toBeInTheDocument();

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("wyłączony przełącznik chowa zależne pole; błąd pola trafia pod pole", async () => {
  previewSettingsGroup.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad Request",
      status: 400,
      code: "invalid",
      detail: "Zła wartość.",
      correlation_id: null,
      errors: [
        { field: "lead_hours", code: "max_value", message: "Najwięcej 168." },
      ],
    }),
  );
  renderForm("en");

  const hours = await screen.findByLabelText("Hours before the visit");
  fireEvent.change(hours, { target: { value: "100" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(await screen.findByText("Najwięcej 168.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("switch"));
  await waitFor(() =>
    expect(screen.queryByLabelText("Hours before the visit")).toBeNull(),
  );
});

test("pole zależne od wartości innego pola widać tylko przy tej wartości", async () => {
  const group: SettingsGroupSchema = {
    ...GROUP,
    key: "booking.offer_probe",
    keys: [
      {
        ...GROUP.keys[0],
        key: "booking.offer_probe.time_model",
        type: "enum",
        default: "slot",
        values: [
          { value: "slot", label: { pl: "Termin", en: "Slot" } },
          { value: "range", label: { pl: "Okres", en: "Range" } },
        ],
        label: { pl: "Model czasu", en: "Time model" },
      },
      {
        ...GROUP.keys[1],
        key: "booking.offer_probe.range_unit",
        type: "enum",
        default: "night",
        minimum: null,
        maximum: null,
        unit: null,
        values: [{ value: "night", label: { pl: "Noc", en: "Night" } }],
        label: { pl: "Jednostka", en: "Unit" },
        depends_on: "booking.offer_probe.time_model == 'range'",
      },
    ],
  };
  getSettingsGroup.mockResolvedValue({
    ...STATE,
    values: { time_model: "slot", range_unit: "night" },
    sources: { time_model: "code", range_unit: "code" },
  });
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <SettingsGroupForm group={group} />
    </NextIntlClientProvider>,
  );

  const model = await screen.findByLabelText("Model czasu");
  await waitFor(() => expect((model as HTMLSelectElement).value).toBe("slot"));
  expect(screen.queryByLabelText("Jednostka")).toBeNull();
  fireEvent.change(model, { target: { value: "range" } });
  expect(await screen.findByLabelText("Jednostka")).toBeInTheDocument();
});

test("zmiana wymagająca kodu 2FA pyta o kod i powtarza zapis", async () => {
  previewSettingsGroup.mockResolvedValue({
    version: "v1",
    values: { enabled: false, lead_hours: 24 },
    changes: { enabled: { from: true, to: false } },
    effects: [],
  });
  updateSettingsGroup
    .mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "Forbidden",
        status: 403,
        code: "step_up_required",
        detail: "Potwierdź kodem.",
        correlation_id: null,
      }),
    )
    .mockResolvedValueOnce({ ...STATE, version: "v2" });
  confirmStepUp.mockResolvedValue(undefined);
  renderForm();

  fireEvent.click(await screen.findByRole("switch"));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  fireEvent.change(await screen.findByLabelText("Kod z aplikacji"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

  await waitFor(() => expect(confirmStepUp).toHaveBeenCalledWith("123456"));
  await waitFor(() => expect(updateSettingsGroup).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("Zapisano ustawienia.")).toBeInTheDocument();
});
