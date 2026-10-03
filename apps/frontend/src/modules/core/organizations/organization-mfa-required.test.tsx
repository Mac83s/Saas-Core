import axe from "axe-core";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { OrganizationMfaRequired } from "./organization-mfa-required";

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  startTotpSetup: vi.fn(),
  confirmTotpSetup: vi.fn(),
}));

function view(locale: "pl" | "en", company = "Domki nad jeziorem") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <OrganizationMfaRequired company={company} />
    </NextIntlClientProvider>,
  );
}

test("says why the company is closed and offers turning 2FA on, in both languages", async () => {
  const { container, unmount } = view("pl");
  expect(
    screen.getByRole("heading", {
      name: "Ta firma wymaga weryfikacji dwuetapowej",
    }),
  ).toBeTruthy();
  expect(screen.getByText(/„Domki nad jeziorem” chroni dostęp/)).toBeTruthy();
  expect(
    screen.getByRole("button", {
      name: "Weryfikacja włączona — przejdź do firmy",
    }),
  ).toBeTruthy();
  expect((await axe.run(container)).violations).toEqual([]);
  unmount();

  view("en");
  expect(
    screen.getByRole("heading", {
      name: "This company requires two-factor sign-in",
    }),
  ).toBeTruthy();
});
