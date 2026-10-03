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

import { ApiProblemError, type AssistantSetup } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SetupProfile } from "./setup-profile";

const api = vi.hoisted(() => ({
  getAssistantSetup: vi.fn(),
  changeAssistantProfile: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

function said<T>(value: T, origin = "owner", confirmed = true) {
  return { value, origin, confirmed };
}

const HEADLINE = "Strzyżenie i koloryzacja w centrum Olsztyna";
const SALON = {
  key: "salon",
  name: said("Salon na Mazurskiej"),
  address: said("ul. Mazurska 4, Olsztyn"),
};
const STUDIO = { key: "studio", name: said("Studio Kortowo") };
/** A place the account already has: a fact, added by the server. */
const OFFICE = {
  key: "place_1",
  name: said("Gabinet na Lipowej", "account"),
  address: said("ul. Lipowa 1, Olsztyn", "account"),
};
const PLACES = [SALON, STUDIO, OFFICE];
const ANIA = {
  key: "ania",
  name: said("Ania"),
  hours: said([
    { weekday: 1, start: "09:00", end: "17:00", place: "salon" },
    { weekday: 0, start: "10:00", end: "14:00", place: "studio" },
  ]),
};
const CUT = {
  key: "cut",
  name: said("Strzyżenie damskie"),
  preset: said("core.specialist_visit"),
  duration_minutes: said(45),
  price: said({ amount: "90.00", currency: "PLN", per: "booking" }),
  places: said(["salon", "studio"]),
  people: said(["ania"]),
};
const COLOUR = {
  key: "colour",
  name: said("Koloryzacja"),
  duration_minutes: said(90, "preset_default", false),
};
const LABELS = {
  categories: { hairdresser: { pl: "Fryzjer", en: "Hairdresser" } },
  presets: {
    "core.specialist_visit": {
      pl: "Wizyta u specjalisty",
      en: "Specialist visit",
    },
  },
};
const SETUP: AssistantSetup = {
  version: 7,
  document: {
    schema: "company-profile.v1",
    company: {
      name: said("Salon Fryzjerski Ania"),
      city: said("Olsztyn"),
      category: said("hairdresser"),
    },
    card: { headline: said(HEADLINE, "assistant", false) },
    languages: said(["pl", "en"]),
    places: PLACES,
    people: [ANIA],
    offers: [CUT, COLOUR],
  },
  labels: LABELS,
  questions: [
    {
      field: "offers.colour.preset",
      kind: "ask",
      reason: "offer_needs_kind",
      proposal: null,
      options: [
        {
          value: "core.specialist_visit",
          label: { pl: "Wizyta u specjalisty", en: "Specialist visit" },
        },
      ],
    },
    {
      field: "card.headline",
      kind: "confirm",
      reason: "assistant",
      proposal: HEADLINE,
      options: [],
    },
  ],
  ready: [
    {
      ref: "place:salon",
      title: { pl: "Zapisz miejsce", en: "Save a place" },
      risk: "apply",
    },
    {
      ref: "card",
      title: { pl: "Zmień wizytówkę", en: "Change the business card" },
      risk: "apply",
    },
  ],
  waiting: [
    {
      ref: "offer:cut",
      reason: "waits",
      waits_for: ["place:salon", "person:ania"],
    },
    { ref: "offer:colour:switch_on", reason: "person_only", waits_for: [] },
  ],
  unsupported: [
    { field: "offers.cut.price", code: "price_list", detail: "" },
    { field: "company.city", code: "city_not_in_catalog", detail: "Olsztyn" },
    { field: "languages", code: "language_not_offered", detail: "de" },
  ],
};
const NOTHING_NOTED: AssistantSetup = {
  version: 0,
  document: { schema: "company-profile.v1" },
  labels: { categories: {}, presets: {} },
  questions: [],
  ready: [],
  waiting: [],
  unsupported: [],
};

/** What the server may send that has no words: nameless entries, keys without
 *  a label, an answer and a step the panel does not know. */
const ROUGH: AssistantSetup = {
  version: 3,
  document: {
    schema: "company-profile.v1",
    company: { category: said("dog-groomer", "assistant", false) },
    places: [{ key: "place_2", address: said("ul. Polna 3, Olsztyn") }],
    people: [{ key: "person_4" }],
    offers: [
      {
        key: "cottage",
        name: said("Domek nad jeziorem"),
        preset: said("core.stay"),
        places: said(["place_2"]),
        inputs: { min_length: said(2), wifi: said("jest") },
      },
    ],
  },
  labels: { categories: LABELS.categories, presets: {} },
  questions: [
    {
      field: "places.place_2.name",
      kind: "ask",
      reason: "place_needs_name",
      proposal: null,
      options: [],
    },
    {
      field: "people.person_4.name",
      kind: "ask",
      reason: "person_needs_name",
      proposal: null,
      options: [],
    },
    {
      field: "company.category",
      kind: "ask",
      reason: "card_needs_category",
      proposal: "hairdresser",
      options: [],
    },
    {
      field: "offers.cottage.inputs.season_dates",
      kind: "ask",
      reason: "preset_requires",
      proposal: null,
      options: [],
    },
    {
      field: "company.category",
      kind: "confirm",
      reason: "assistant",
      proposal: "dog-groomer",
      options: [],
    },
  ],
  ready: [],
  waiting: [
    { ref: "place:place_2", reason: "command_missing", waits_for: [] },
    { ref: "site:home", reason: "command_missing", waits_for: [] },
  ],
  unsupported: [
    {
      field: "company.category",
      code: "category_unknown",
      detail: "dog-groomer",
    },
  ],
};
const KEYS =
  /place_2|person_4|cottage|core\.stay|dog-groomer|hairdresser|min_length|wifi|season_dates|site:home/;

function problem(code: string, status: number) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: null,
    correlation_id: null,
  });
}

function view(locale: "pl" | "en" = "pl", revision = 0) {
  const page = (shown: number) => (
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SetupProfile conversationId="c1" revision={shown} />
    </NextIntlClientProvider>
  );
  const rendered = render(page(revision));
  return {
    ...rendered,
    settle: (next: number) => rendered.rerender(page(next)),
  };
}

/** The row of one value: its label, the value, where it came from, its buttons. */
function row(label: string, block: HTMLElement = document.body) {
  const term = within(block)
    .getAllByText(label)
    .find((node) => node.tagName === "DT");
  return within(term?.parentElement as HTMLElement);
}

/** The block of one place, person or offer, by its name. */
function entry(name: string) {
  return screen.getByRole("heading", { name }).closest("div")
    ?.parentElement as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getAssistantSetup.mockResolvedValue(SETUP);
  api.changeAssistantProfile.mockResolvedValue({});
});

test("the profile says in words what is known, from whom, and what is still open", async () => {
  const { container } = view();

  expect(await screen.findByText("Salon Fryzjerski Ania")).toBeInTheDocument();
  expect(api.getAssistantSetup).toHaveBeenCalledWith("c1", expect.anything());
  // Each value with where it came from; an unconfirmed one says so.
  const headline = row("Jedno zdanie o firmie");
  expect(headline.getByText(HEADLINE)).toBeInTheDocument();
  expect(headline.getByText("Propozycja asystenta")).toBeInTheDocument();
  expect(headline.getByText("Do potwierdzenia")).toBeInTheDocument();
  const city = row("Miasto");
  expect(city.getByText("Twoje słowa")).toBeInTheDocument();
  expect(city.queryByText("Do potwierdzenia")).toBeNull();
  expect(city.queryByRole("button", { name: /Potwierdź/ })).toBeNull();
  expect(row("Języki").getByText("polski, angielski")).toBeInTheDocument();
  // Keys are shown as the names they stand for.
  expect(row("Kategoria").getByText("Fryzjer")).toBeInTheDocument();
  expect(
    row("Godziny pracy").getByText(
      "pon. 10:00–14:00 — Studio Kortowo wt. 09:00–17:00 — Salon na Mazurskiej",
    ),
  ).toBeInTheDocument();
  const cut = entry("Strzyżenie damskie");
  expect(
    row("Rodzaj rezerwacji", cut).getByText("Wizyta u specjalisty"),
  ).toBeInTheDocument();
  expect(row("Czas trwania", cut).getByText("45 minut")).toBeInTheDocument();
  expect(
    row("Cena", cut).getByText("90,00 PLN / rezerwacja"),
  ).toBeInTheDocument();
  expect(
    row("Miejsca", cut).getByText("Salon na Mazurskiej, Studio Kortowo"),
  ).toBeInTheDocument();
  expect(row("Osoby", cut).getByText("Ania")).toBeInTheDocument();
  expect(
    row("Czas trwania", entry("Koloryzacja")).getByText("Wartość domyślna"),
  ).toBeInTheDocument();
  // Only plain text and whole numbers are corrected here.
  expect(
    screen.getByRole("button", { name: "Popraw: Miasto" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Popraw: Cena/ })).toBeNull();

  for (const line of [
    "Jak klienci rezerwują usługę „Koloryzacja”.",
    "Do potwierdzenia: Jedno zdanie o firmie.",
    "Zapisz miejsce: Salon na Mazurskiej",
    "Zmień wizytówkę",
    "Asystent zaproponuje to w rozmowie. Nic się nie zmieni bez Twojej zgody.",
    "W kolejnym kroku: usługa „Strzyżenie damskie”. Najpierw: miejsce „Salon na Mazurskiej”, osoba „Ania”.",
    "Usługę „Koloryzacja” włączasz samodzielnie w panelu.",
    "Ceny usługi „Strzyżenie damskie” nie da się jeszcze zapisać.",
    "Miasta „Olsztyn” nie ma na liście miast katalogu firm.",
    "Język niemiecki nie jest jeszcze dostępny.",
  ]) {
    expect(screen.getByText(line)).toBeInTheDocument();
  }
  // Never a key, a ref or a code.
  expect(container.innerHTML).not.toMatch(
    /core\.specialist_visit|offer:|place:|place_1|price_list|hairdresser/,
  );
  expect((await axe.run(container)).violations).toEqual([]);
});

test("with nothing noted the profile says so and shows no empty list", async () => {
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  const { container } = view("en");

  expect(
    await screen.findByText(
      "The assistant has not noted anything about the company yet.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Company profile — what I know and what is missing"),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("heading")).toHaveLength(1);
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText(/company's account/)).toBeNull();
  expect((await axe.run(container)).violations).toEqual([]);
});

test("a key, a nameless entry and an unknown answer or step are said in words, never shown", async () => {
  api.getAssistantSetup.mockResolvedValue(ROUGH);
  const labelled = view();

  await screen.findByRole("heading", { name: "Domek nad jeziorem" });
  const cottage = entry("Domek nad jeziorem");
  // A key without a label is an unknown value, not the key.
  expect(row("Kategoria").getByText("nieznana wartość")).toBeInTheDocument();
  expect(
    row("Rodzaj rezerwacji", cottage).getByText("nieznana wartość"),
  ).toBeInTheDocument();
  // An entry without a name is „bez nazwy” wherever it is named.
  expect(screen.getAllByRole("heading", { name: "bez nazwy" })).toHaveLength(2);
  expect(row("Miejsca", cottage).getByText("bez nazwy")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Usuń: miejsce „bez nazwy”" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Popraw: Adres — bez nazwy" }),
  ).toBeInTheDocument();
  // What a kind of booking asks for: the product's own by name, else neutral.
  expect(row("Najkrótszy pobyt", cottage).getByText("2")).toBeInTheDocument();
  expect(
    row("Dodatkowa informacja", cottage).getByText("jest"),
  ).toBeInTheDocument();
  for (const line of [
    "Jak nazywa się miejsce, w którym firma przyjmuje.",
    "Jak nazywa się osoba z zespołu.",
    "W jakiej kategorii pokazać firmę w katalogu (propozycja: Fryzjer).",
    "Usługa „Domek nad jeziorem” wymaga jeszcze: Daty sezonów.",
    "Do potwierdzenia: Kategoria.",
    "Produkt jeszcze tego nie umie: miejsce „bez nazwy”.",
    "Produkt jeszcze tego nie umie: inne ustawienie.",
    "Wybranej kategorii nie ma w katalogu firm.",
  ]) {
    expect(screen.getByText(line)).toBeInTheDocument();
  }
  expect(labelled.container.innerHTML).not.toMatch(KEYS);
  labelled.unmount();

  // A proposed category without a label is left out, not shown by its key.
  api.getAssistantSetup.mockResolvedValue({
    ...ROUGH,
    labels: { categories: {}, presets: {} },
  });
  const bare = view();
  expect(
    await screen.findByText("W jakiej kategorii pokazać firmę w katalogu."),
  ).toBeInTheDocument();
  expect(bare.container.innerHTML).not.toMatch(KEYS);
});

test("a fact of the account is shown but not changed here; the owner's own value is", async () => {
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  const office = entry("Gabinet na Lipowej");
  expect(row("Nazwa", office).getByText("Z konta firmy")).toBeInTheDocument();
  expect(
    row("Adres", office).getByText("ul. Lipowa 1, Olsztyn"),
  ).toBeInTheDocument();
  // Neither the place nor its values: no „Popraw”, no „Usuń”.
  expect(within(office).queryByRole("button")).toBeNull();
  expect(
    screen.getByText(
      "To, co pochodzi z konta firmy, zmienisz w ustawieniach w panelu.",
    ),
  ).toBeInTheDocument();

  const salon = within(entry("Salon na Mazurskiej"));
  for (const name of [
    "Usuń: miejsce „Salon na Mazurskiej”",
    "Popraw: Adres — Salon na Mazurskiej",
    "Usuń: Adres — Salon na Mazurskiej",
  ]) {
    expect(salon.getByRole("button", { name })).toBeEnabled();
  }
});

test("„Potwierdź” keeps the same value as the owner's own, and the profile is read again", async () => {
  let saved: (value: unknown) => void = () => undefined;
  api.changeAssistantProfile.mockReturnValue(
    new Promise((resolve) => {
      saved = resolve;
    }),
  );
  view();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Potwierdź: Jedno zdanie o firmie",
    }),
  );

  expect(api.changeAssistantProfile).toHaveBeenCalledWith(
    { card: { headline: said(HEADLINE, "owner", true) } },
    7,
    expect.any(String),
  );
  // No second change on top of one that is being saved.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Usuń: Miasto" })).toBeDisabled(),
  );
  saved({});
  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Usuń: Miasto" })).toBeEnabled(),
  );
});

test("a value inside a list is saved with the lists whole", async () => {
  view();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Potwierdź: Czas trwania — Koloryzacja",
    }),
  );

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      {
        places: PLACES,
        people: [ANIA],
        offers: [CUT, { ...COLOUR, duration_minutes: said(90, "owner", true) }],
      },
      7,
      expect.any(String),
    ),
  );
});

test("„Usuń” on a place takes it out with every reference to it", async () => {
  view();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Usuń: miejsce „Studio Kortowo”",
    }),
  );

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      {
        places: [SALON, OFFICE],
        people: [
          {
            ...ANIA,
            hours: said([
              { weekday: 1, start: "09:00", end: "17:00", place: "salon" },
            ]),
          },
        ],
        offers: [{ ...CUT, places: said(["salon"]) }, COLOUR],
      },
      7,
      expect.any(String),
    ),
  );
});

test("„Usuń” on a person takes them out of the offers, and on a value removes the field", async () => {
  view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Usuń: osoba „Ania”" }),
  );
  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      {
        places: PLACES,
        people: [],
        offers: [{ ...CUT, people: said([]) }, COLOUR],
      },
      7,
      expect.any(String),
    ),
  );
  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(2));

  fireEvent.click(screen.getByRole("button", { name: "Usuń: Miasto" }));
  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenLastCalledWith(
      { company: { city: null } },
      7,
      expect.any(String),
    ),
  );
});

test("„Popraw” saves the typed text as the owner's confirmed value; an empty one is not saved", async () => {
  view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Popraw: Miasto" }),
  );
  const input = screen.getByLabelText("Miasto");
  expect(input).toHaveValue("Olsztyn");
  expect(input).toHaveFocus();

  fireEvent.change(input, { target: { value: "  " } });
  expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  fireEvent.submit(input);
  expect(api.changeAssistantProfile).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: " Ostróda " } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      { company: { city: said("Ostróda", "owner", true) } },
      7,
      expect.any(String),
    ),
  );
  // Saved: the input closes and the focus is back on the button.
  await waitFor(() => expect(screen.queryByLabelText("Miasto")).toBeNull());
  expect(screen.getByRole("button", { name: "Popraw: Miasto" })).toHaveFocus();
});

test("„Popraw” takes a whole number for a duration, and „Anuluj” leaves the value alone", async () => {
  view();
  const name = "Czas trwania — Strzyżenie damskie";

  fireEvent.click(
    await screen.findByRole("button", { name: `Popraw: ${name}` }),
  );
  fireEvent.change(screen.getByLabelText(name), { target: { value: "1,5" } });
  expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
  expect(screen.queryByLabelText(name)).toBeNull();
  expect(api.changeAssistantProfile).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: `Popraw: ${name}` }));
  expect(screen.getByLabelText(name)).toHaveValue("45");
  fireEvent.change(screen.getByLabelText(name), { target: { value: "60" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      {
        places: PLACES,
        people: [ANIA],
        offers: [{ ...CUT, duration_minutes: said(60, "owner", true) }, COLOUR],
      },
      7,
      expect.any(String),
    ),
  );
});

test("a profile changed in the meantime is read again and the person is told", async () => {
  api.changeAssistantProfile.mockRejectedValue(
    problem("assistant_profile_version_conflict", 409),
  );
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  api.getAssistantSetup.mockResolvedValue({
    ...SETUP,
    version: 8,
    document: {
      ...SETUP.document,
      company: { name: said("Salon Ania"), city: said("Ostróda") },
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Usuń: Miasto" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Profil firmy zmienił się w międzyczasie. Sprawdź go i spróbuj ponownie.",
  );
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(2);
  expect(row("Miasto").getByText("Ostróda")).toBeInTheDocument();

  // The next change names the version now shown.
  api.changeAssistantProfile.mockResolvedValue({});
  fireEvent.click(screen.getByRole("button", { name: "Usuń: Miasto" }));
  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenLastCalledWith(
      { company: { city: null } },
      8,
      expect.any(String),
    ),
  );
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});

test("a change the server refuses is said plainly and nothing is read again", async () => {
  api.changeAssistantProfile.mockRejectedValue(problem("invalid", 400));
  view("en");

  fireEvent.click(await screen.findByRole("button", { name: "Remove: City" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The change could not be saved. Try again.",
  );
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(1);
  expect(row("City").getByText("Olsztyn")).toBeInTheDocument();
});

test("the profile is read again when the conversation settles", async () => {
  const page = view();

  await screen.findByText("Salon Fryzjerski Ania");
  page.settle(1);

  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(2));
});
