import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import messages from "../../../../messages/pl.json";
import { ItemTranslationsSheet } from "./item-translations-sheet";

const api = vi.hoisted(() => ({
  getBookingItemTranslations: vi.fn(),
  previewBookingItemTranslation: vi.fn(),
  updateBookingItemTranslation: vi.fn(),
}));

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

const SERVICE = "33333333-3333-4333-8333-333333333333";

function german(text: string, status = "fresh", version = 1) {
  return {
    kind: "service",
    item_id: SERVICE,
    source_locale: "pl",
    languages: [
      {
        locale: "de",
        version,
        units: [
          {
            key: "name",
            source_text: "Strzyżenie",
            text,
            status,
            origin: text ? "human" : "",
          },
        ],
      },
    ],
  };
}

function open() {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <ItemTranslationsSheet
        item={{ kind: "service", id: SERVICE, name: "Strzyżenie" }}
        onClose={() => undefined}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("the sheet shows the source above the field and saves at the version read", async () => {
  api.getBookingItemTranslations.mockResolvedValueOnce(
    german("", "missing", 0),
  );
  api.getBookingItemTranslations.mockResolvedValue(german("Haarschnitt"));
  api.updateBookingItemTranslation.mockResolvedValue({});
  open();
  expect(
    await screen.findByText("Brak — pokaże się tekst źródłowy"),
  ).not.toBeNull();
  expect(screen.getByText("Strzyżenie", { selector: "p" })).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Nazwa"), {
    target: { value: "Haarschnitt" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.updateBookingItemTranslation).toHaveBeenCalled(),
  );
  const [kind, id, locale, input] =
    api.updateBookingItemTranslation.mock.calls[0];
  expect([kind, id, locale, input]).toEqual([
    "service",
    SERVICE,
    "de",
    { texts: { name: "Haarschnitt" }, expected_version: 0 },
  ]);
  expect(await screen.findByText("Zapisano.")).not.toBeNull();
  expect(screen.getByText("Aktualne")).not.toBeNull();
});

test("a version changed meanwhile asks to refresh", async () => {
  api.getBookingItemTranslations.mockResolvedValue(german("Haarschnitt"));
  api.updateBookingItemTranslation.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "booking_version_conflict",
    } as ConstructorParameters<typeof ApiProblemError>[0]),
  );
  open();
  fireEvent.change(await screen.findByLabelText("Nazwa"), {
    target: { value: "Schnitt" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
  expect(
    await screen.findByText("Ktoś zmienił to tłumaczenie — odśwież."),
  ).not.toBeNull();
});
