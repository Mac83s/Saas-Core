import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import { PublicContactForm } from "./public-contact-form";

const { submitPublicSiteInquiry } = vi.hoisted(() => ({
  submitPublicSiteInquiry: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  submitPublicSiteInquiry,
}));
const publicationId = "10000000-0000-4000-8000-000000000001";

beforeEach(() => {
  vi.resetAllMocks();
  submitPublicSiteInquiry.mockResolvedValue({
    accepted: true,
    reference: "10000000-0000-4000-8000-000000000002",
  });
});
afterEach(cleanup);

function renderForm(locale: "pl" | "en" = "pl") {
  return render(
    <PublicContactForm
      blockPosition={2}
      locale={locale}
      path="/kontakt/"
      publicationId={publicationId}
    />,
  );
}
function fill(locale: "pl" | "en" = "pl") {
  fireEvent.change(
    screen.getByRole("textbox", {
      name: locale === "pl" ? "Imię i nazwisko" : "Full name",
    }),
    { target: { value: "Example Visitor" } },
  );
  fireEvent.change(
    screen.getByRole("textbox", {
      name: locale === "pl" ? "Adres e-mail" : "Email address",
    }),
    { target: { value: "visitor@example.test" } },
  );
  fireEvent.change(
    screen.getByRole("textbox", {
      name: locale === "pl" ? "Wiadomość" : "Message",
    }),
    { target: { value: "Please send more information." } },
  );
}
function send(locale: "pl" | "en" = "pl") {
  fireEvent.click(
    screen.getByRole("button", {
      name: locale === "pl" ? "Wyślij wiadomość" : "Send message",
    }),
  );
}
function problem(status: number) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Failure",
    status,
    code: "site_inquiry_failed",
    detail: "Private server detail must not be shown",
    correlation_id: null,
  });
}

test.each(["pl", "en"] as const)(
  "formularz %s jest dostępny i przyjmuje wiadomość bez obietnicy dostarczenia e-maila",
  async (locale) => {
    const result = renderForm(locale);
    expect(screen.getByRole("form")).toHaveAttribute("method", "post");
    expect((await axe.run(result.container)).violations).toHaveLength(0);
    fill(locale);
    send(locale);
    await waitFor(() =>
      expect(submitPublicSiteInquiry).toHaveBeenCalledTimes(1),
    );
    expect(submitPublicSiteInquiry).toHaveBeenCalledWith(
      {
        path: "/kontakt/",
        publication_id: publicationId,
        block_position: 2,
        name: "Example Visitor",
        email: "visitor@example.test",
        phone: "",
        message: "Please send more information.",
        website: "",
      },
      expect.any(String),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      locale === "pl"
        ? "Twoja wiadomość została przyjęta"
        : "Your message has been received",
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect((await axe.run(result.container)).violations).toHaveLength(0);
  },
);

test.each(["pl", "en"] as const)(
  "waliduje wymagane pola i adres e-mail w %s",
  async (locale) => {
    const result = renderForm(locale);
    send(locale);
    const name = screen.getByRole("textbox", {
      name: locale === "pl" ? "Imię i nazwisko" : "Full name",
    });
    await waitFor(() => expect(name).toHaveAttribute("aria-invalid", "true"));
    expect(name).toHaveAccessibleDescription(
      locale === "pl" ? "Uzupełnij to pole." : "Complete this field.",
    );
    expect(submitPublicSiteInquiry).not.toHaveBeenCalled();
    fill(locale);
    fireEvent.change(
      screen.getByRole("textbox", {
        name: locale === "pl" ? "Adres e-mail" : "Email address",
      }),
      { target: { value: "bad-email" } },
    );
    send(locale);
    expect(
      await screen.findByText(
        locale === "pl"
          ? "Podaj poprawny adres e-mail."
          : "Enter a valid email address.",
      ),
    ).not.toBeNull();
    expect((await axe.run(result.container)).violations).toHaveLength(0);
  },
);

test("ponawia identyczną treść z tym samym kluczem także po zmianie i przywróceniu treści", async () => {
  submitPublicSiteInquiry.mockRejectedValue(new Error("offline"));
  renderForm();
  fill();
  send();
  await screen.findByRole("alert");
  const key = submitPublicSiteInquiry.mock.calls[0][1];
  send();
  await waitFor(() => expect(submitPublicSiteInquiry).toHaveBeenCalledTimes(2));
  expect(submitPublicSiteInquiry.mock.calls[1][1]).toBe(key);
  await screen.findByRole("alert");
  fireEvent.change(screen.getByRole("textbox", { name: "Wiadomość" }), {
    target: { value: "Different message" },
  });
  send();
  await waitFor(() => expect(submitPublicSiteInquiry).toHaveBeenCalledTimes(3));
  expect(submitPublicSiteInquiry.mock.calls[2][1]).not.toBe(key);
  await screen.findByRole("alert");
  fireEvent.change(screen.getByRole("textbox", { name: "Wiadomość" }), {
    target: { value: "Please send more information." },
  });
  send();
  await waitFor(() => expect(submitPublicSiteInquiry).toHaveBeenCalledTimes(4));
  expect(submitPublicSiteInquiry.mock.calls[3][1]).toBe(key);
});

test.each([
  [400, "Sprawdź wprowadzone dane"],
  [403, "nie przyjmuje obecnie wiadomości"],
  [404, "nie przyjmuje obecnie wiadomości"],
  [409, "Odśwież stronę"],
  [413, "Wiadomość jest zbyt długa"],
  [429, "Odczekaj chwilę"],
  [500, "Spróbuj ponownie"],
])(
  "obsługuje Problem Details %i i zachowuje treść do ponowienia",
  async (status, text) => {
    submitPublicSiteInquiry.mockRejectedValue(problem(status));
    renderForm();
    fill();
    send();
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.getByRole("textbox", { name: "Wiadomość" })).toHaveValue(
      "Please send more information.",
    );
    expect(screen.queryByText(/Private server detail/)).toBeNull();
  },
);

test("blokuje powtórny submit w trakcie wysyłania i wysyła opcjonalny telefon", async () => {
  let resolve!: (value: { accepted: boolean; reference: string }) => void;
  submitPublicSiteInquiry.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  renderForm();
  fill();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Telefon (opcjonalnie)" }),
    { target: { value: "+48 000 000 000" } },
  );
  send();
  const button = await screen.findByRole("button", { name: "Wysyłanie…" });
  expect(button).toBeDisabled();
  fireEvent.submit(screen.getByRole("form"));
  await waitFor(() => expect(submitPublicSiteInquiry).toHaveBeenCalledTimes(1));
  expect(button).toBeDisabled();
  expect(screen.getByRole("form")).toHaveAttribute("aria-busy", "true");
  expect(submitPublicSiteInquiry.mock.calls[0][0].phone).toBe(
    "+48 000 000 000",
  );
  resolve({ accepted: true, reference: "receipt" });
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent(
      "Twoja wiadomość została przyjęta",
    ),
  );
});
