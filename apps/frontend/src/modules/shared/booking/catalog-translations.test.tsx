import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { CatalogTranslations } from "./catalog-translations";

const api = vi.hoisted(() => ({
  getPublicLocales: vi.fn(),
  getTranslationOffer: vi.fn(),
  quoteTranslation: vi.fn(),
}));

// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const COMPANY = "66666666-6666-4666-8666-666666666666";

function view() {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <CatalogTranslations organizationId={COMPANY} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getTranslationOffer.mockResolvedValue({ available: true });
});

test("the whole catalogue is quoted once per other language of the company", async () => {
  api.getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en", "de"],
  });
  api.quoteTranslation.mockResolvedValue({ units: 0 });

  view();
  fireEvent.click(
    await screen.findByRole("button", { name: "Przetłumacz brakujące" }),
  );

  await waitFor(() =>
    expect(api.quoteTranslation).toHaveBeenCalledWith([
      {
        source_key: "booking.catalog",
        object_id: COMPANY,
        locale: "en",
        basis: "published",
      },
      {
        source_key: "booking.catalog",
        object_id: COMPANY,
        locale: "de",
        basis: "published",
      },
    ]),
  );
  expect(
    await screen.findByText("Wszystko jest już przetłumaczone."),
  ).toBeTruthy();
});

test("a company with one language sees nothing about other languages", async () => {
  api.getPublicLocales.mockResolvedValue({ public_locales: ["pl"] });

  const { container } = view();

  await waitFor(() => expect(api.getPublicLocales).toHaveBeenCalled());
  expect(container.textContent).toBe("");
});
