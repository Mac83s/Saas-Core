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

async function reachMfaStep() {
  loginAccount.mockResolvedValue({ kind: "mfa_required" });
  renderWithMessages(<LoginForm />);
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "user@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Hasło"), {
    target: { value: "Bezpieczne-Haslo-2026!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
  return screen.findByLabelText("Kod MFA");
}

test("nie tworzy sesji w UI przed zakończeniem challenge MFA", async () => {
  completeMfaLogin.mockResolvedValue({ email: "user@example.com" });
  const input = await reachMfaStep();
  expect(replace).not.toHaveBeenCalled();
  // One labelled control for the six slots, hinted as a one-time code.
  expect(input).toHaveAttribute("autocomplete", "one-time-code");
  expect(input).toHaveAttribute("inputmode", "numeric");

  fireEvent.change(input, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zaloguj" }));

  await waitFor(() => expect(completeMfaLogin).toHaveBeenCalledWith("123456"));
  expect(replace).toHaveBeenCalledWith("/panel");
});

test("wklejony kod wypełnia wszystkie sloty, a litery są odrzucane", async () => {
  const input = await reachMfaStep();
  fireEvent.change(input, { target: { value: "12ab" } });
  expect(input).toHaveValue("");
  fireEvent.paste(input, {
    clipboardData: { getData: () => "654321" },
  });
  fireEvent.change(input, { target: { value: "654321" } });
  expect(input).toHaveValue("654321");
});

test("za krótki kod nie jest wysyłany i pokazuje błąd", async () => {
  const input = await reachMfaStep();
  fireEvent.change(input, { target: { value: "123" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zaloguj" }));
  expect(
    await screen.findByText("Wpisz 6 cyfr z aplikacji."),
  ).toBeInTheDocument();
  expect(completeMfaLogin).not.toHaveBeenCalled();
});

test("odrzucony kod pokazuje błąd i oznacza pole", async () => {
  completeMfaLogin.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "invalid_mfa_code",
      status: 400,
      code: "invalid_mfa_code",
      detail: "invalid_mfa_code",
      correlation_id: null,
    }),
  );
  const input = await reachMfaStep();
  fireEvent.change(input, { target: { value: "000000" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zaloguj" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input.getAttribute("aria-describedby")).toBeTruthy();
});

test("kod odzyskiwania to zwykłe pole tekstowe, a przełączenie czyści wpisaną wartość", async () => {
  completeMfaLogin.mockResolvedValue({ email: "user@example.com" });
  const input = await reachMfaStep();
  fireEvent.change(input, { target: { value: "123456" } });

  fireEvent.click(
    screen.getByRole("button", { name: "Użyj kodu odzyskiwania" }),
  );
  const recovery = await screen.findByLabelText("Kod odzyskiwania");
  expect(recovery).toHaveValue("");
  expect(recovery).not.toHaveAttribute("inputmode", "numeric");
  fireEvent.change(recovery, { target: { value: "ABCD-EFGH-JKLM-NPQR" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i zaloguj" }));
  await waitFor(() =>
    expect(completeMfaLogin).toHaveBeenCalledWith("ABCD-EFGH-JKLM-NPQR"),
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Użyj kodu z aplikacji" }),
  );
  expect(await screen.findByLabelText("Kod MFA")).toHaveValue("");
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

  // The language reads as its name before the list is ever opened, not „pl”.
  expect(
    screen.getByRole("combobox", { name: "Język komunikacji" }),
  ).toHaveTextContent("Polski");
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

test("gdzie można założyć konto samemu, ekran logowania prowadzi do rejestracji jak dotąd", () => {
  renderWithMessages(<LoginForm returnTo="/invitations/accept?token=abc" />);

  expect(screen.getByRole("link", { name: "Utwórz konto" })).toHaveAttribute(
    "href",
    "/register",
  );
});
