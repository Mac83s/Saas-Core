import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { LoginForm, RegistrationForm } from "./auth-forms";

const { replace, refresh, loginAccount, completeMfaLogin, registerAccount } =
  vi.hoisted(() => ({
    replace: vi.fn(),
    refresh: vi.fn(),
    loginAccount: vi.fn(),
    completeMfaLogin: vi.fn(),
    registerAccount: vi.fn(),
  }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  loginAccount,
  completeMfaLogin,
  registerAccount,
  beginTotpSetup: vi.fn(),
}));

beforeEach(() => vi.clearAllMocks());

test("nie tworzy sesji w UI przed zakończeniem challenge MFA", async () => {
  loginAccount.mockResolvedValue({ kind: "mfa_required" });
  completeMfaLogin.mockResolvedValue({ email: "user@example.com" });
  render(<LoginForm />);

  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "user@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Hasło"), {
    target: { value: "Bezpieczne-Haslo-2026!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

  expect(
    await screen.findByLabelText("Kod MFA lub odzyskiwania"),
  ).toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Kod MFA lub odzyskiwania"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zaloguj" }));

  await waitFor(() => expect(completeMfaLogin).toHaveBeenCalledWith("123456"));
  expect(replace).toHaveBeenCalledWith("/panel");
});

test("pokazuje równoważny komunikat rejestracji zwrócony przez API", async () => {
  registerAccount.mockResolvedValue(
    "Jeżeli konto może zostać utworzone, wysłaliśmy instrukcję.",
  );
  render(<RegistrationForm />);

  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "new@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Hasło"), {
    target: { value: "Bezpieczne-Haslo-2026!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Utwórz konto" }));

  expect(
    await screen.findByText(
      "Jeżeli konto może zostać utworzone, wysłaliśmy instrukcję.",
    ),
  ).toBeInTheDocument();
});
