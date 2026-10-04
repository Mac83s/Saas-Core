import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { ProfileTranslations } from "./profile-translations";

const api = vi.hoisted(() => ({
  getProfileTranslations: vi.fn(),
  getTranslationOffer: vi.fn(),
  updateProfileTranslation: vi.fn(),
}));

// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

vi.mock("#i18n/navigation", () => ({
  Link: ({
    children,
    ...props
  }: ComponentProps<"a"> & { children: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));

const CARD = "55555555-5555-4555-8555-555555555555";
const LINK = "link/0123456789ab";

function card(languages: unknown[]) {
  return { source_locale: "pl", languages };
}

const GERMAN = {
  locale: "de",
  headline: "",
  bio: "",
  link_labels: {},
  allow_headline_fallback: true,
  allow_bio_fallback: true,
  version: 0,
  units: [
    {
      key: "headline",
      source_text: "Fryzjer",
      text: "",
      status: "missing",
      origin: "",
    },
    {
      key: LINK,
      source_text: "Cennik",
      text: "",
      status: "missing",
      origin: "",
    },
  ],
};

function show(canManage = true) {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <ProfileTranslations canManage={canManage} profileId={CARD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("a company with one language is told where to add another", async () => {
  api.getProfileTranslations.mockResolvedValue(card([]));
  show();
  expect(
    await screen.findByText("Dodaj język w Ustawienia → Języki"),
  ).not.toBeNull();
});

test("the card's German is saved at its version, link labels by their link", async () => {
  api.getProfileTranslations.mockResolvedValue(card([GERMAN]));
  api.getTranslationOffer.mockRejectedValue(new Error("not composed"));
  api.updateProfileTranslation.mockResolvedValue({});
  show();
  fireEvent.change(await screen.findByLabelText("Nagłówek"), {
    target: { value: "Friseur" },
  });
  fireEvent.change(screen.getByLabelText("Etykieta linku „Cennik”"), {
    target: { value: "Preise" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
  await waitFor(() => expect(api.updateProfileTranslation).toHaveBeenCalled());
  expect(api.updateProfileTranslation.mock.calls[0]).toEqual([
    CARD,
    "de",
    {
      expected_version: 0,
      headline: "Friseur",
      link_labels: { [LINK]: "Preise" },
    },
  ]);
  // No engine in this deployment: no button, no line about it.
  expect(screen.queryByText("Przetłumacz brakujące")).toBeNull();
});

test("while the platform has not switched translation on, one line says so", async () => {
  api.getProfileTranslations.mockResolvedValue(card([GERMAN]));
  api.getTranslationOffer.mockResolvedValue({
    available: false,
    reasons: ["model_not_selected"],
  });
  show();
  expect(
    await screen.findByText(/Automatyczne tłumaczenie będzie dostępne/),
  ).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: "Przetłumacz brakujące" }),
  ).toBeNull();
});
