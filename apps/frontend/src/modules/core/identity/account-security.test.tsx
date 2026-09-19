import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import messages from "../../../../messages/pl.json";
import { PasswordCard, TwoFactorCard } from "./account-security";

const api = vi.hoisted(() => ({
  beginTotpSetup: vi.fn(),
  confirmTotpSetup: vi.fn(),
  requestPasswordReset: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const problem = (status: number, code: string) =>
  new ApiProblemError({
    type: "about:blank",
    title: code,
    status,
    code,
    detail: code,
    correlation_id: null,
  });

function renderPl(element: ReactElement) {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      {element}
    </NextIntlClientProvider>,
  );
}

const noContrast = { rules: { "color-contrast": { enabled: false } } };

beforeEach(() => vi.clearAllMocks());

test("hasło zmienia się linkiem wysłanym na adres konta", async () => {
  api.requestPasswordReset.mockResolvedValue("ok");
  const { container } = renderPl(
    <PasswordCard email="anna.kowalska@example.com" />,
  );

  const send = screen.getByRole("button", {
    name: "Wyślij link do zmiany hasła",
  });
  fireEvent.click(send);

  await waitFor(() =>
    expect(api.requestPasswordReset).toHaveBeenCalledWith({
      email: "anna.kowalska@example.com",
    }),
  );
  expect(
    await screen.findByText(/Link jest w drodze na anna.kowalska@example.com/),
  ).toBeInTheDocument();
  expect(send).toBeDisabled();
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
});

test("weryfikacja dwuetapowa: klucz, kod, kody odzyskiwania", async () => {
  api.beginTotpSetup.mockResolvedValue({
    secret: "JBSWY3DPEHPK3PXP",
    provisioning_uri:
      "otpauth://totp/SaaS:anna.kowalska%40example.com?secret=JBSWY3DPEHPK3PXP",
  });
  api.confirmTotpSetup
    .mockRejectedValueOnce(problem(400, "invalid_mfa_code"))
    .mockResolvedValueOnce({
      status: "mfa_enabled",
      recovery_codes: ["K7PQ-M2XD", "R9TA-4HWN"],
    });
  const { container } = renderPl(<TwoFactorCard />);

  fireEvent.click(
    screen.getByRole("button", { name: "Włącz weryfikację dwuetapową" }),
  );

  expect(await screen.findByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Otwórz aplikację uwierzytelniającą" }),
  ).toHaveAttribute("href", expect.stringMatching(/^otpauth:\/\/totp\//));
  const code = screen.getByLabelText("Kod potwierdzający");
  await waitFor(() => expect(code).toHaveFocus());
  expect((await axe.run(container, noContrast)).violations).toEqual([]);

  fireEvent.change(code, { target: { value: "12345" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i włącz" }));
  expect(await screen.findByText("Wpisz 6 cyfr z aplikacji.")).toBeVisible();
  expect(api.confirmTotpSetup).not.toHaveBeenCalled();

  fireEvent.change(code, { target: { value: "000000" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i włącz" }));
  expect(
    await screen.findByText("Kod uwierzytelniający jest nieprawidłowy."),
  ).toBeInTheDocument();

  fireEvent.change(code, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i włącz" }));
  const codes = await screen.findByRole("list", { name: "Kody odzyskiwania" });
  expect(codes).toHaveTextContent("K7PQ-M2XD");
  expect(api.confirmTotpSetup).toHaveBeenLastCalledWith("123456");

  fireEvent.click(screen.getByRole("button", { name: "Kody zapisane" }));
  expect(
    await screen.findByText(
      "Weryfikacja dwuetapowa jest włączona na tym koncie.",
    ),
  ).toHaveFocus();
});

test("włączona wcześniej weryfikacja nie zaczyna konfiguracji od nowa", async () => {
  api.beginTotpSetup.mockRejectedValue(problem(409, "mfa_already_enabled"));
  renderPl(<TwoFactorCard />);

  fireEvent.click(
    screen.getByRole("button", { name: "Włącz weryfikację dwuetapową" }),
  );

  expect(
    await screen.findByText(
      "Weryfikacja dwuetapowa jest włączona na tym koncie.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Kod potwierdzający")).toBeNull();
});
