import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import messages from "../../../../messages/pl.json";
import { LoginForm, RegistrationForm } from "./auth-forms";

const { replace, refresh, loginAccount, completeMfaLogin, registerAccount } =
  vi.hoisted(() => ({
    replace: vi.fn(),
    refresh: vi.fn(),
    loginAccount: vi.fn(),
    completeMfaLogin: vi.fn(),
    registerAccount: vi.fn(),
  }));

vi.mock("#i18n/navigation", () => ({
  Link: "a",
  useRouter: () => ({ replace, refresh }),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  loginAccount,
  completeMfaLogin,
  registerAccount,
}));

beforeEach(() => vi.clearAllMocks());

function renderWithMessages(element: ReactElement) {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      {element}
    </NextIntlClientProvider>,
  );
}

test("nie tworzy sesji w UI przed zakończeniem challenge MFA", async () => {
  loginAccount.mockResolvedValue({ kind: "mfa_required" });
  completeMfaLogin.mockResolvedValue({ email: "user@example.com" });
  renderWithMessages(<LoginForm />);

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

test("konto operatora bez MFA dostaje komunikat zamiast ustawiania MFA samym hasłem", async () => {
  // An operator's first MFA is set on the server (platform settings 0c):
  // with a password alone nobody may set a second factor of their own.
  loginAccount.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "mfa_setup_required",
      status: 403,
      code: "mfa_setup_required",
      detail: "mfa_setup_required",
      correlation_id: null,
    }),
  );
  renderWithMessages(<LoginForm />);

  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "admin@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Hasło"), {
    target: { value: "Bezpieczne-Haslo-2026!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

  expect(
    await screen.findByText(/Pierwsze ustawia administrator serwera/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("img")).toBeNull();
  expect(replace).not.toHaveBeenCalled();
});

test("pokazuje równoważny komunikat rejestracji zwrócony przez API", async () => {
  registerAccount.mockResolvedValue(
    "Jeżeli konto może zostać utworzone, wysłaliśmy instrukcję.",
  );
  renderWithMessages(<RegistrationForm />);

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
