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
import { SiteOnboardingWizard } from "./site-onboarding";

const {
  completeSiteOnboarding,
  getSiteOnboarding,
  getSubdomainAvailability,
  saveSiteOnboarding,
} = vi.hoisted(() => ({
  completeSiteOnboarding: vi.fn(),
  getSiteOnboarding: vi.fn(),
  getSubdomainAvailability: vi.fn(),
  saveSiteOnboarding: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  completeSiteOnboarding,
  getSiteOnboarding,
  getSubdomainAvailability,
  saveSiteOnboarding,
}));

const initialState = {
  id: null,
  version: 0,
  step: "address",
  name: "",
  subdomain_label: "",
  default_locale: "pl",
  platform_domain: "sites.example.test",
  hostname: "",
  site_id: null,
  updated_at: null,
};

const site = {
  id: "019ff20d-a000-7000-8000-000000000010",
  name: "Moja firma",
  slug: "moja-firma",
  default_locale: "pl",
  current_publication_id: null,
  created_at: "2026-08-13T12:00:00Z",
  updated_at: "2026-08-13T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  getSiteOnboarding.mockResolvedValue(initialState);
  getSubdomainAvailability.mockResolvedValue({
    requested_label: "Moja Firma",
    normalized_label: "moja-firma",
    hostname: "moja-firma.sites.example.test",
    available: true,
    reason: "available",
    suggestion: "",
  });
  saveSiteOnboarding.mockImplementation(async (input) => ({
    ...initialState,
    id: "019ff20d-a000-7000-8000-000000000011",
    version: input.version + 1,
    step: input.step,
    name: input.name,
    subdomain_label: input.subdomain_label,
    default_locale: input.default_locale,
    hostname: input.subdomain_label
      ? `${input.subdomain_label}.sites.example.test`
      : "",
    updated_at: "2026-08-13T12:00:00Z",
  }));
  completeSiteOnboarding.mockResolvedValue(site);
});

afterEach(cleanup);

test("prowadzi po polsku przez adres, dane i podsumowanie bez naruszeń axe", async () => {
  const onCompleted = vi.fn();
  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SiteOnboardingWizard onCompleted={onCompleted} />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Wybierz adres swojej strony" }),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  fireEvent.change(screen.getByLabelText("Preferowany adres"), {
    target: { value: "Moja Firma" },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Sprawdź adres i przejdź dalej",
    }),
  );

  expect(
    await screen.findByRole("heading", { name: "Dodaj podstawowe dane" }),
  ).not.toBeNull();
  expect(getSubdomainAvailability).toHaveBeenCalledWith("Moja Firma");
  fireEvent.change(screen.getByLabelText("Nazwa widoczna dla klientów"), {
    target: { value: "Moja firma" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Przejdź do podsumowania" }),
  );

  expect(
    await screen.findByRole("heading", { name: "Sprawdź i utwórz stronę" }),
  ).not.toBeNull();
  expect(screen.getByText("moja-firma.sites.example.test")).not.toBeNull();
  expect(screen.getByText("Opcjonalnie")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Utwórz moją stronę" }));

  await waitFor(() => expect(completeSiteOnboarding).toHaveBeenCalledOnce());
  expect(onCompleted).toHaveBeenCalledWith(site);
});

test("wznawia zapisany krok danych po angielsku", async () => {
  getSiteOnboarding.mockResolvedValueOnce({
    ...initialState,
    id: "019ff20d-a000-7000-8000-000000000012",
    version: 3,
    step: "details",
    name: "Saved business",
    subdomain_label: "saved-business",
    default_locale: "en",
    hostname: "saved-business.sites.example.test",
    updated_at: "2026-08-13T12:00:00Z",
  });

  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <SiteOnboardingWizard onCompleted={vi.fn()} />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Add the essentials" }),
  ).not.toBeNull();
  expect(screen.getByDisplayValue("Saved business")).not.toBeNull();
  expect(
    screen.getByText(/saved-business\.sites\.example\.test/),
  ).not.toBeNull();
  expect(getSubdomainAvailability).not.toHaveBeenCalled();
});

test("pokazuje zajęty adres i pozwala użyć bezpiecznej propozycji", async () => {
  getSubdomainAvailability
    .mockResolvedValueOnce({
      requested_label: "zajety",
      normalized_label: "zajety",
      hostname: "zajety.sites.example.test",
      available: false,
      reason: "taken",
      suggestion: "zajety-2",
    })
    .mockResolvedValueOnce({
      requested_label: "zajety-2",
      normalized_label: "zajety-2",
      hostname: "zajety-2.sites.example.test",
      available: true,
      reason: "available",
      suggestion: "",
    });

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SiteOnboardingWizard onCompleted={vi.fn()} />
    </NextIntlClientProvider>,
  );
  const input = await screen.findByLabelText("Preferowany adres");
  fireEvent.change(input, { target: { value: "zajety" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Sprawdź adres i przejdź dalej" }),
  );

  expect(await screen.findByText("Ten adres jest już zajęty.")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Użyj propozycji: zajety-2" }),
  );
  expect(input).toHaveValue("zajety-2");
  fireEvent.click(
    screen.getByRole("button", { name: "Sprawdź adres i przejdź dalej" }),
  );
  expect(
    await screen.findByRole("heading", { name: "Dodaj podstawowe dane" }),
  ).not.toBeNull();
});

test("pokazuje konflikt wersji i jawnie wczytuje najnowszy postęp", async () => {
  saveSiteOnboarding.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "site_onboarding_version_conflict",
      detail: "Changed elsewhere",
      correlation_id: null,
    }),
  );
  getSiteOnboarding.mockResolvedValueOnce(initialState).mockResolvedValueOnce({
    ...initialState,
    version: 2,
    step: "details",
    name: "Nowsza firma",
    subdomain_label: "nowsza-firma",
    hostname: "nowsza-firma.sites.example.test",
  });

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SiteOnboardingWizard onCompleted={vi.fn()} />
    </NextIntlClientProvider>,
  );
  fireEvent.change(await screen.findByLabelText("Preferowany adres"), {
    target: { value: "moja-firma" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Sprawdź adres i przejdź dalej" }),
  );

  expect(
    await screen.findByText(
      "Dane zmieniły się w międzyczasie. Odśwież widok i spróbuj ponownie.",
    ),
  ).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Wczytaj najnowszy postęp" }),
  );
  expect(
    await screen.findByRole("heading", { name: "Dodaj podstawowe dane" }),
  ).not.toBeNull();
  expect(screen.getByDisplayValue("Nowsza firma")).not.toBeNull();
});
