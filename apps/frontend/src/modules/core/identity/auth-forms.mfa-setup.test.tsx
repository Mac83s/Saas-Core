import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import messages from "../../../../messages/pl.json";
import { LoginForm, LoginScreen } from "./auth-forms";

// The first MFA of an operator set inside the login form: the step a stack
// opens with `OPERATOR_MFA_SETUP_AT_LOGIN` (ADR-023, uzupełnienie 2026-10-06).
// The API answers the sign-in with 403 `mfa_setup_at_login`; the form then
// shows the panel's two-factor card and only the saved recovery codes lead on.

const api = vi.hoisted(() => ({
  loginAccount: vi.fn(),
  completeMfaLogin: vi.fn(),
  beginTotpSetup: vi.fn(),
  confirmTotpSetup: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn() }));

vi.mock("#i18n/navigation", () => ({
  Link: "a",
  useRouter: () => router,
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

function signIn() {
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "admin@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Hasło"), {
    target: { value: "Bezpieczne-Haslo-2026!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
}

const noContrast = { rules: { "color-contrast": { enabled: false } } };
const QR = "Kod QR do zeskanowania w aplikacji uwierzytelniającej";

beforeEach(() => {
  vi.clearAllMocks();
  api.loginAccount.mockRejectedValue(problem(403, "mfa_setup_at_login"));
  api.beginTotpSetup.mockResolvedValue({
    secret: "JBSWY3DPEHPK3PXP",
    provisioning_uri:
      "otpauth://totp/SaaS:admin%40example.com?secret=JBSWY3DPEHPK3PXP",
  });
});

test("operator bez MFA ustawia je w formularzu logowania: kod QR, kod z aplikacji, kody odzyskiwania", async () => {
  api.confirmTotpSetup
    .mockRejectedValueOnce(problem(400, "invalid_mfa_code"))
    .mockResolvedValueOnce({
      status: "mfa_enabled",
      recovery_codes: ["K7PQ-M2XD", "R9TA-4HWN"],
    });
  const { container } = renderPl(<LoginForm returnTo="/panel/platforma" />);

  signIn();

  // The answer is a step of the form, not an error under the password.
  fireEvent.click(
    await screen.findByRole("button", { name: "Włącz weryfikację dwuetapową" }),
  );
  expect(screen.queryByLabelText("Hasło")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();

  expect(
    (await screen.findByRole("img", { name: QR })).firstElementChild?.tagName,
  ).toBe("svg");
  expect(screen.getByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
  expect(api.beginTotpSetup).toHaveBeenCalledTimes(1);
  expect((await axe.run(container, noContrast)).violations).toEqual([]);

  const code = screen.getByLabelText("Kod potwierdzający");
  fireEvent.change(code, { target: { value: "000000" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i włącz" }));
  expect(
    await screen.findByText("Kod uwierzytelniający jest nieprawidłowy."),
  ).toBeInTheDocument();
  expect(router.replace).not.toHaveBeenCalled();

  fireEvent.change(code, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź i włącz" }));
  expect(
    await screen.findByRole("list", { name: "Kody odzyskiwania" }),
  ).toHaveTextContent("R9TA-4HWN");
  expect(api.confirmTotpSetup).toHaveBeenLastCalledWith("123456");
  // The session exists by now, but the codes are shown once: the person
  // leaves this screen with their own click, not by a redirect.
  expect(router.replace).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Kody zapisane" }));
  expect(router.replace).toHaveBeenCalledWith("/panel/platforma");
  expect(router.refresh).toHaveBeenCalledTimes(1);
  // Nothing went through the code challenge of an account that has MFA.
  expect(api.completeMfaLogin).not.toHaveBeenCalled();
});

test("nieudany start konfiguracji zostawia operatora na kroku z komunikatem, bez sesji", async () => {
  // The challenge expired, or the stack switched the door off meanwhile.
  api.beginTotpSetup.mockRejectedValue(problem(403, "not_authenticated"));
  renderPl(<LoginForm />);

  signIn();
  fireEvent.click(
    await screen.findByRole("button", { name: "Włącz weryfikację dwuetapową" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się skonfigurować weryfikacji. Spróbuj ponownie.",
  );
  expect(screen.queryByRole("img", { name: QR })).toBeNull();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Włącz weryfikację dwuetapową" }),
    ).toBeEnabled(),
  );
  expect(router.replace).not.toHaveBeenCalled();
});

test("ekran logowania zmienia nagłówek, gdy otwiera się krok ustawiania MFA", async () => {
  renderPl(<LoginScreen />);
  expect(
    screen.getByText("Podaj adres e-mail i hasło swojego konta."),
  ).toBeInTheDocument();

  signIn();
  await screen.findByRole("button", { name: "Włącz weryfikację dwuetapową" });

  expect(
    screen.getByRole("heading", { name: "Ustaw weryfikację dwuetapową" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Podaj adres e-mail i hasło swojego konta."),
  ).toBeNull();
  expect(screen.queryByText("Zaloguj się")).toBeNull();
});
