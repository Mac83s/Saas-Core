import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type BookingFormField,
  type BookingFormFieldList,
  type ServiceSetup,
} from "@saas-core/api-client";
import polishMessages from "../../../../../messages/pl.json";
import { OfferFieldsDialog } from "./offer-fields-dialog";

const { api } = vi.hoisted(() => ({
  api: {
    createBookingFormField: vi.fn(),
    listBookingFormFields: vi.fn(),
    updateBookingFormField: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const RENTAL = "0199a000-0000-7000-8000-0000000000a1";
const OTHER = "0199a000-0000-7000-8000-0000000000a2";
const service = {
  id: RENTAL,
  name: "Wypożyczenie roweru",
  active: true,
  version: 3,
} as unknown as ServiceSetup;

const limits: BookingFormFieldList["limits"] = {
  max_fields: 20,
  min_options: 2,
  max_options: 20,
  max_option_length: 80,
  max_name_length: 160,
  max_answer_length: 200,
  max_long_answer_length: 500,
  kinds: [
    { value: "text", label: { pl: "Tekst", en: "Text" } },
    { value: "long_text", label: { pl: "Dłuższy tekst", en: "Long text" } },
    { value: "number", label: { pl: "Liczba", en: "Number" } },
    { value: "date", label: { pl: "Data", en: "Date" } },
    { value: "choice", label: { pl: "Wybór z listy", en: "Choice" } },
    {
      value: "consent",
      label: { pl: "Zgoda (pole do zaznaczenia)", en: "Consent" },
    },
  ],
};

function field(overrides: Partial<BookingFormField> = {}): BookingFormField {
  return {
    id: "0199a000-0000-7000-8000-0000000000f1",
    service_id: RENTAL,
    name: "Numer prawa jazdy",
    kind: "text",
    options: [],
    mandatory: true,
    mandatory_for_staff: true,
    position: 1,
    active: true,
    version: 1,
    ...overrides,
  };
}

function problem(code: string, errors: object[] = []) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status: code === "booking_version_conflict" ? 409 : 400,
    code,
    detail: "",
    correlation_id: null,
    errors,
  } as ConstructorParameters<typeof ApiProblemError>[0]);
}

function show() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <OfferFieldsDialog
        finalFocus={null}
        onOpenChange={() => undefined}
        service={service}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listBookingFormFields.mockResolvedValue({
    items: [
      field(),
      field({
        id: "0199a000-0000-7000-8000-0000000000f2",
        name: "Rama",
        kind: "choice",
        options: ["Damska", "Męska"],
        mandatory: false,
        position: 2,
        active: false,
      }),
      // Another offer's field is not this dialog's.
      field({
        id: "0199a000-0000-7000-8000-0000000000f3",
        service_id: OTHER,
        name: "Pytanie innej usługi",
      }),
    ],
    limits,
  });
});

test("the offer's fields are listed with what they take, and the dialog passes axe", async () => {
  show();

  const licence = (await screen.findByText("Numer prawa jazdy")).closest(
    "tr",
  ) as HTMLElement;
  expect(licence).toHaveTextContent("Tekst · obowiązkowe");
  const frame = screen.getByText("Rama").closest("tr") as HTMLElement;
  expect(frame).toHaveTextContent(
    "Wybór z listy · Damska / Męska · nieobowiązkowe",
  );
  expect(within(frame).getByText("Wyłączone")).toBeInTheDocument();
  expect(screen.queryByText("Pytanie innej usługi")).toBeNull();
  // What not to ask is said where the questions are written.
  expect(screen.getByText(/Nie zbieraj tu danych o zdrowiu/)).toBeVisible();
  const results = await axe.run(document.body);
  expect(results.violations).toEqual([]);
});

test("a new choice needs its options and is saved for this offer", async () => {
  api.createBookingFormField.mockResolvedValue(
    field({ name: "Rozmiar kasku", kind: "choice", options: ["S", "M"] }),
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj pole" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Nowe pole formularza",
  });
  const inside = within(dialog);

  fireEvent.change(inside.getByLabelText("Rodzaj odpowiedzi"), {
    target: { value: "choice" },
  });
  fireEvent.change(inside.getByLabelText("Pytanie"), {
    target: { value: " Rozmiar kasku " },
  });
  fireEvent.change(inside.getByLabelText("Możliwości do wyboru"), {
    target: { value: "S\n" },
  });
  fireEvent.click(inside.getByRole("button", { name: "Zapisz" }));
  expect(
    await inside.findByText(
      "Podaj co najmniej dwie możliwości, po jednej w wierszu.",
    ),
  ).toBeInTheDocument();
  expect(api.createBookingFormField).not.toHaveBeenCalled();

  fireEvent.change(inside.getByLabelText("Możliwości do wyboru"), {
    target: { value: "S\n\n M \n" },
  });
  fireEvent.change(inside.getByLabelText("Czy klient musi odpowiedzieć?"), {
    target: { value: "mandatory" },
  });
  fireEvent.click(inside.getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createBookingFormField).toHaveBeenCalledTimes(1),
  );
  expect(api.createBookingFormField.mock.calls[0][0]).toEqual({
    service_id: RENTAL,
    name: "Rozmiar kasku",
    kind: "choice",
    options: ["S", "M"],
    mandatory: true,
    mandatory_for_staff: true,
  });
  expect(await screen.findByText("Dodano: Rozmiar kasku.")).toBeInTheDocument();
});

test("a consent asks for its wording, and a refusal is said in the panel's words", async () => {
  api.createBookingFormField.mockRejectedValue(
    problem("validation_error", [
      { field: "name", code: "name_taken", message: "…" },
    ]),
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj pole" }));
  const inside = within(
    await screen.findByRole("dialog", { name: "Nowe pole formularza" }),
  );
  fireEvent.change(inside.getByLabelText("Rodzaj odpowiedzi"), {
    target: { value: "consent" },
  });
  // The journal keeps the wording: the dialog says so.
  expect(inside.getByText(/w dzienniku zgód/)).toBeInTheDocument();
  fireEvent.change(inside.getByLabelText("Treść zgody"), {
    target: { value: "Znam regulamin obiektu" },
  });
  fireEvent.click(inside.getByRole("button", { name: "Zapisz" }));
  expect(
    await inside.findByText("Ta usługa ma już takie pole."),
  ).toBeInTheDocument();
});

test("a field is switched off at the version shown, never deleted", async () => {
  api.updateBookingFormField.mockResolvedValue(field({ active: false }));
  show();
  const row = (await screen.findByText("Numer prawa jazdy")).closest(
    "tr",
  ) as HTMLElement;
  fireEvent.click(
    within(row).getByRole("button", {
      name: "Więcej akcji: Numer prawa jazdy",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Wyłącz" }));
  await waitFor(() =>
    expect(api.updateBookingFormField).toHaveBeenCalledTimes(1),
  );
  expect(api.updateBookingFormField.mock.calls[0].slice(0, 2)).toEqual([
    "0199a000-0000-7000-8000-0000000000f1",
    { active: false, expected_version: 1 },
  ]);
  expect(
    await screen.findByText("Wyłączono: Numer prawa jazdy."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: /Usuń/ })).toBeNull();
});

test("a mandatory field can leave the team free, and a consent cannot", async () => {
  api.createBookingFormField.mockResolvedValue(
    field({
      name: "Liczba sztuk",
      kind: "long_text",
      mandatory_for_staff: false,
    }),
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj pole" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Nowe pole formularza",
  });
  const inside = within(dialog);
  const team = "Obowiązkowe także, gdy rezerwację wpisuje zespół";

  // Optional: the second control is not there; the kind list names the long text.
  expect(inside.queryByLabelText(team)).toBeNull();
  expect(
    within(inside.getByLabelText("Rodzaj odpowiedzi")).getByRole("option", {
      name: "Dłuższy tekst",
    }),
  ).toBeInTheDocument();
  fireEvent.change(inside.getByLabelText("Czy klient musi odpowiedzieć?"), {
    target: { value: "mandatory" },
  });
  // On by default, with its line of help; a consent is the customer's alone.
  const control = inside.getByLabelText(team);
  expect(control).toBeChecked();
  expect(
    inside.getByText(/Wyłącz, jeśli klient musi odpowiedzieć sam/),
  ).toBeVisible();
  const results = await axe.run(dialog);
  expect(results.violations).toEqual([]);
  fireEvent.change(inside.getByLabelText("Rodzaj odpowiedzi"), {
    target: { value: "consent" },
  });
  expect(inside.queryByLabelText(team)).toBeNull();

  fireEvent.change(inside.getByLabelText("Rodzaj odpowiedzi"), {
    target: { value: "long_text" },
  });
  fireEvent.click(inside.getByLabelText(team));
  fireEvent.change(inside.getByLabelText("Pytanie"), {
    target: { value: "Liczba sztuk" },
  });
  fireEvent.click(inside.getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createBookingFormField).toHaveBeenCalledTimes(1),
  );
  expect(api.createBookingFormField.mock.calls[0][0]).toMatchObject({
    kind: "long_text",
    mandatory: true,
    mandatory_for_staff: false,
  });
});
