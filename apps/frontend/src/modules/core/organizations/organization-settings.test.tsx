import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type OrganizationSummary,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import { OrganizationSettings } from "./organization-settings";

const { updateCurrentOrganization, router } = vi.hoisted(() => ({
  updateCurrentOrganization: vi.fn(),
  router: { refresh: vi.fn() },
}));

vi.mock("#i18n/navigation", () => ({ useRouter: () => router }));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  updateCurrentOrganization,
}));

const COMPANY: OrganizationSummary = {
  id: "019c5f87-fce8-739b-b960-b7a195bfc298",
  name: "Usługi Kowalski",
  slug: "uslugi-kowalski",
  workspace_kind: "business",
  organization_type: "business",
  status: "active",
  default_locale: "pl",
  timezone: "Europe/Warsaw",
  currency: "PLN",
  version: 3,
  membership_status: "active",
  role: "owner",
  permissions: ["organization.settings.manage"],
  active: true,
};

function renderSettings(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? messages : englishMessages}
    >
      <OrganizationSettings organization={COMPANY} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("zapisuje tylko zmienione pola, z wersją, i odświeża menu", async () => {
  updateCurrentOrganization.mockResolvedValue({
    ...COMPANY,
    name: "Kowalski i Syn",
    currency: "EUR",
    version: 4,
  });
  const { container } = renderSettings();

  expect(
    (screen.getByLabelText("Strefa czasowa") as HTMLInputElement).value,
  ).toBe("Europe/Warsaw");
  fireEvent.change(screen.getByLabelText("Nazwa firmy"), {
    target: { value: "Kowalski i Syn" },
  });
  fireEvent.change(screen.getByLabelText("Waluta"), {
    target: { value: "EUR" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

  await waitFor(() =>
    expect(updateCurrentOrganization).toHaveBeenCalledWith({
      name: "Kowalski i Syn",
      currency: "EUR",
      version: 3,
    }),
  );
  expect(await screen.findByText("Zapisano dane firmy.")).toBeInTheDocument();
  expect(router.refresh).toHaveBeenCalledOnce();

  // The next save names the version the first one returned.
  fireEvent.change(screen.getByLabelText("Domyślny język"), {
    target: { value: "en" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  await waitFor(() =>
    expect(updateCurrentOrganization).toHaveBeenLastCalledWith({
      default_locale: "en",
      version: 4,
    }),
  );

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("konflikt wersji prosi o odświeżenie zamiast nadpisać cudze zmiany", async () => {
  updateCurrentOrganization.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "organization_version_conflict",
      detail: "Organizacja została zmieniona.",
      correlation_id: null,
    }),
  );
  renderSettings();

  fireEvent.change(screen.getByLabelText("Nazwa firmy"), {
    target: { value: "Kowalski i Syn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Ktoś w międzyczasie zmienił dane firmy.",
  );
  expect(router.refresh).not.toHaveBeenCalled();
});

test("za krótka nazwa nie trafia do API", async () => {
  renderSettings("en");

  fireEvent.change(screen.getByLabelText("Company name"), {
    target: { value: " K " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  expect(
    await screen.findByText("Enter the company name (at least 2 characters)."),
  ).toBeInTheDocument();
  expect(updateCurrentOrganization).not.toHaveBeenCalled();
});
