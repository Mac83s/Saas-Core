import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";

// A deployment none of whose organization types may be signed up for
// (ADR-050): a content product whose only workspace is the operator's.
vi.mock("#lib/organization-types", async (original) => ({
  ...(await original<typeof import("#lib/organization-types")>()),
  selfSignupTypes: [],
}));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
class NotFound extends Error {}
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new NotFound();
  },
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
}));

const { LoginForm } = await import("./auth-forms");
const { registrationHref } = await import("#lib/sign-up");
const { default: RegisterPage } =
  await import("../../../app/[locale]/(auth)/register/page");

const INVITATION = "/invitations/accept?token=abc";

function view(element: ReactElement) {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      {element}
    </NextIntlClientProvider>,
  );
}

test("ekran logowania nie proponuje rejestracji, której nie ma", () => {
  view(<LoginForm />);

  expect(
    screen.getByRole("link", { name: "Nie pamiętam hasła" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Utwórz konto" }),
  ).not.toBeInTheDocument();
});

test("/register nie podaje formularza — odpowiada jak strona, której w deploymencie nie ma", async () => {
  expect(registrationHref()).toBeNull();
  expect(registrationHref("/panel")).toBeNull();
  await expect(
    RegisterPage({ searchParams: Promise.resolve({}) }),
  ).rejects.toBeInstanceOf(NotFound);
  await expect(
    RegisterPage({ searchParams: Promise.resolve({ next: "/panel" }) }),
  ).rejects.toBeInstanceOf(NotFound);
});

test("zaproszona osoba nadal może założyć konto: przychodzi z adresu zaproszenia i go zachowuje", async () => {
  view(<LoginForm returnTo={INVITATION} />);

  expect(screen.getByRole("link", { name: "Utwórz konto" })).toHaveAttribute(
    "href",
    `/register?next=${encodeURIComponent(INVITATION)}`,
  );
  await expect(
    RegisterPage({ searchParams: Promise.resolve({ next: INVITATION }) }),
  ).resolves.toBeTruthy();
});
