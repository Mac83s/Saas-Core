import axe from "axe-core";
import {
  configure,
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

// A row's menu opens through a portal: beside another gate and a rebuild the
// default second is not always enough, and a different test fails each time.
configure({ asyncUtilTimeout: 5000 });

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
const COMPANY = {
  name: said("Salon Fryzjerski Ania"),
  city: said("Olsztyn"),
  category: said("hairdresser"),
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
    company: COMPANY,
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
      field: "offers.colour.duration_minutes",
      kind: "confirm",
      reason: "preset_default",
      proposal: 90,
      options: [],
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
        inputs: {
          min_length: said(2),
          wifi: said("jest"),
          season_dates: said([{ from: "05-01", to: "09-30" }]),
        },
      },
      { key: "offer_9", duration_minutes: said(30) },
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
      field: "offers.cottage.inputs.photos",
      kind: "ask",
      reason: "preset_requires",
      proposal: null,
      options: [],
    },
    {
      field: "offers.offer_9.name",
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
  /place_2|person_4|cottage|offer_9|core\.stay|dog-groomer|hairdresser|min_length|wifi|season_dates|05-01|site:home/;
/** The panel's hours never break at the dash (U+2060 on both sides). */
const JOIN = String.fromCharCode(0x2060);

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

/** The notes with the document changed, as a save and a read leave them. */
function setupWith(document: Record<string, unknown>): AssistantSetup {
  return { ...SETUP, document: { ...SETUP.document, ...document } };
}

/** Beside the conversation the notes are open; under it they start closed. */
function view(locale: "pl" | "en" = "pl", beside = true) {
  const page = (revision: number) => (
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SetupProfile beside={beside} conversationId="c1" revision={revision} />
    </NextIntlClientProvider>
  );
  const rendered = render(page(0));
  return {
    ...rendered,
    settle: (next: number) => rendered.rerender(page(next)),
  };
}

/** The row of one value: its label, the value, where it came from, its controls. */
function rowOf(label: string, block: HTMLElement = document.body) {
  const term = within(block)
    .getAllByText(label)
    .find((node) => node.tagName === "DT");
  return term?.parentElement as HTMLElement;
}

function row(label: string, block?: HTMLElement) {
  return within(rowOf(label, block));
}

/** The block of one place, person or offer, by its name. */
function entry(name: string) {
  return screen.getByRole("heading", { name }).closest("div")
    ?.parentElement as HTMLElement;
}

function button(name: string) {
  return screen.getByRole("button", { name });
}

/** Opens a row's „…” and answers the item of its menu. Beside another gate
 * a click can reach the „…” before its menu is ready and is lost for good:
 * click until the menu says it is open, then wait for its items. */
async function opened(more: string, item: string) {
  await waitFor(() => {
    const trigger = button(more);
    if (trigger.getAttribute("aria-expanded") !== "true") {
      fireEvent.click(trigger);
    }
    expect(screen.getByRole("menuitem", { name: item })).toBeInTheDocument();
  });
  return screen.getByRole("menuitem", { name: item });
}

/** Picks an action behind a row's „…”. */
async function choose(more: string, item: string) {
  fireEvent.click(await opened(more, item));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getAssistantSetup.mockResolvedValue(SETUP);
  api.changeAssistantProfile.mockResolvedValue({});
});

test("the notes say in words what is known, from whom, and what is still open", async () => {
  const { container } = view();

  expect(await screen.findByText("Salon Fryzjerski Ania")).toBeInTheDocument();
  expect(api.getAssistantSetup).toHaveBeenCalledWith("c1", expect.anything());
  expect(
    screen.getByText("Notatki o firmie — co już wiadomo i czego brakuje"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "To notatki z rozmowy. W koncie firmy nic się nie zmieni bez Twojej zgody.",
    ),
  ).toBeInTheDocument();
  // A value says where it came from only when that is not the owner; an
  // unconfirmed one says so, and is the only kind with an action in sight.
  const headline = row("Jedno zdanie o firmie");
  expect(headline.getByText(HEADLINE)).toBeInTheDocument();
  expect(headline.getByText("propozycja asystenta")).toBeInTheDocument();
  expect(headline.getByText("Do potwierdzenia")).toBeInTheDocument();
  expect(
    headline.getByRole("button", { name: "Potwierdź: Jedno zdanie o firmie" }),
  ).toBeInTheDocument();
  expect(rowOf("Miasto").querySelector("dd")).toHaveTextContent(/^Olsztyn$/);
  expect(row("Miasto").getAllByRole("button")).toEqual([
    button("Więcej: Miasto"),
  ]);
  expect(screen.queryByRole("button", { name: /^(Popraw|Usuń: Miasto)/ })).toBe(
    null,
  );
  expect(row("Języki").getByText("polski, angielski")).toBeInTheDocument();
  // Keys are shown as the names they stand for.
  expect(row("Kategoria").getByText("Fryzjer")).toBeInTheDocument();
  expect(
    row("Godziny pracy").getByText(
      `pon. 10:00${JOIN}–${JOIN}14:00 — Studio Kortowo wt. 09:00${JOIN}–${JOIN}17:00 — Salon na Mazurskiej`,
    ),
  ).toBeInTheDocument();
  const cut = entry("Strzyżenie damskie");
  expect(
    row("Rodzaj rezerwacji", cut).getByText("Wizyta u specjalisty"),
  ).toBeInTheDocument();
  expect(row("Czas trwania", cut).getByText("45 minut")).toBeInTheDocument();
  expect(
    row("Cena", cut).getByText("90,00 zł za rezerwację"),
  ).toBeInTheDocument();
  expect(
    row("Miejsca", cut).getByText("Salon na Mazurskiej, Studio Kortowo"),
  ).toBeInTheDocument();
  expect(row("Osoby", cut).getByText("Ania")).toBeInTheDocument();
  expect(
    row("Czas trwania", entry("Koloryzacja")).getByText("wartość domyślna"),
  ).toBeInTheDocument();

  for (const heading of [
    "Co już wiadomo",
    "O co asystent jeszcze zapyta",
    "Gotowe do ustawienia",
    "Co zostaje na później",
    "Czego nie da się jeszcze ustawić",
  ]) {
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  }
  for (const line of [
    "Jak klienci rezerwują usługę „Koloryzacja”?",
    "Do potwierdzenia: „Czas trwania — Koloryzacja”.",
    "Do potwierdzenia: „Jedno zdanie o firmie”.",
    "Zapisz miejsce: Salon na Mazurskiej",
    "Zmień wizytówkę",
    "Asystent zaproponuje to w rozmowie. Nic się nie zmieni bez Twojej zgody.",
    "W kolejnym kroku: usługa „Strzyżenie damskie”. Najpierw: miejsce „Salon na Mazurskiej”, osoba „Ania”.",
    "Usługę „Koloryzacja” włączasz samodzielnie w panelu.",
    "Ceny usługi „Strzyżenie damskie” asystent jeszcze nie zapisuje — wpiszesz ją w cenniku usługi: Ustawienia › Usługi i grafik.",
    "Miasta „Olsztyn” nie ma na liście miast katalogu firm. Wybierz najbliższe z listy w Wizytówce.",
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

test("with nothing noted the notes say so and show no empty list", async () => {
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  const { container } = view("en");

  expect(
    await screen.findByText(
      "The assistant has not noted anything about the company yet.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Notes about the company — what is known and what is missing",
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("heading")).toHaveLength(1);
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText(/company's account is changed/)).toBeNull();
  expect((await axe.run(container)).violations).toEqual([]);
});

test("under the conversation the notes start closed and say whether they need the person", async () => {
  const polish = view("pl", false);

  const summary = await screen.findByText(
    "Notatki o firmie · 2 do potwierdzenia · 1 pytanie",
  );
  expect(summary.tagName).toBe("SUMMARY");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect((await axe.run(polish.container)).violations).toEqual([]);
  polish.unmount();

  const english = view("en", false);
  expect(
    await screen.findByText(
      "Notes about the company · 2 to confirm · 1 question",
    ),
  ).toBeInTheDocument();
  english.unmount();

  // Nothing to confirm and nothing asked: the name alone.
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  view("pl", false);
  await screen.findByText("Asystent nie zanotował jeszcze nic o firmie.");
  expect(screen.getByText("Notatki o firmie").tagName).toBe("SUMMARY");
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
  // An entry without a name is „bez nazwy”, in plain words, wherever it is named.
  expect(screen.getAllByRole("heading", { name: "Bez nazwy" })).toHaveLength(3);
  expect(row("Miejsca", cottage).getByText("bez nazwy")).toBeInTheDocument();
  expect(button("Usuń: miejsce bez nazwy")).toBeInTheDocument();
  expect(button("Więcej: Adres — bez nazwy")).toBeInTheDocument();
  // What a kind of booking asks for: the known by name and with their unit,
  // the rest under one neutral label; an answer with no words is „zanotowane”.
  expect(
    row("Najkrótszy pobyt", cottage).getByText("2 noce"),
  ).toBeInTheDocument();
  expect(
    row("Dodatkowa informacja", cottage).getByText("jest"),
  ).toBeInTheDocument();
  expect(
    row("Daty sezonów", cottage).getByText("zanotowane"),
  ).toBeInTheDocument();
  for (const line of [
    "Jak nazywa się miejsce, w którym firma przyjmuje klientów?",
    "Jak nazywa się osoba z zespołu?",
    "W jakiej kategorii pokazać firmę w katalogu? Propozycja: Fryzjer.",
    "Usługa „Domek nad jeziorem” wymaga jeszcze pola „Zdjęcia”.",
    "Usługa bez nazwy wymaga jeszcze pola „Nazwa”.",
    "Do potwierdzenia: „Kategoria”.",
    "Tego asystent jeszcze nie ustawia: miejsce bez nazwy. Zrobisz to w panelu.",
    "Tego asystent jeszcze nie ustawia: inne ustawienie. Zrobisz to w panelu.",
    "Wybranej kategorii nie ma w katalogu firm.",
  ]) {
    expect(screen.getByText(line)).toBeInTheDocument();
  }
  expect(labelled.container.innerHTML).not.toMatch(KEYS);
  expect((await axe.run(labelled.container)).violations).toEqual([]);
  labelled.unmount();

  // A proposed category without a label is left out, not shown by its key.
  api.getAssistantSetup.mockResolvedValue({
    ...ROUGH,
    labels: { categories: {}, presets: {} },
  });
  const bare = view();
  expect(
    await screen.findByText("W jakiej kategorii pokazać firmę w katalogu?"),
  ).toBeInTheDocument();
  expect(bare.container.innerHTML).not.toMatch(KEYS);
});

test("a fact of the account is shown but not changed here; the owner's own value is", async () => {
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  const office = entry("Gabinet na Lipowej");
  expect(row("Nazwa", office).getByText("z konta firmy")).toBeInTheDocument();
  expect(
    row("Adres", office).getByText("ul. Lipowa 1, Olsztyn"),
  ).toBeInTheDocument();
  // Neither the place nor its values: no „…”, no „Usuń”.
  expect(within(office).queryByRole("button")).toBeNull();
  expect(
    screen.getByText(
      "To, co pochodzi z konta firmy, zmienisz w ustawieniach w panelu.",
    ),
  ).toBeInTheDocument();

  expect(button("Usuń: miejsce „Salon na Mazurskiej”")).toBeEnabled();
  // Text is corrected or removed; a price only removed.
  await opened("Więcej: Adres — Salon na Mazurskiej", "Popraw");
  expect(screen.getByRole("menuitem", { name: "Usuń" })).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

  await opened("Więcej: Cena — Strzyżenie damskie", "Usuń");
  expect(screen.queryByRole("menuitem", { name: "Popraw" })).toBeNull();
});

test("„Potwierdź” keeps the same value as the owner's own; the focus goes to the row's „…”", async () => {
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
  await waitFor(() => expect(button("Więcej: Miasto")).toBeDisabled());
  expect(screen.queryByText("Zapisano w notatkach.")).toBeNull();

  api.getAssistantSetup.mockResolvedValue(
    setupWith({ card: { headline: said(HEADLINE, "owner", true) } }),
  );
  saved({});

  expect(await screen.findByRole("status")).toHaveTextContent(
    "Zapisano w notatkach.",
  );
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(2);
  // The button that was pressed is gone with the value's „Do potwierdzenia”.
  expect(
    screen.queryByRole("button", { name: "Potwierdź: Jedno zdanie o firmie" }),
  ).toBeNull();
  await waitFor(() =>
    expect(button("Więcej: Jedno zdanie o firmie")).toHaveFocus(),
  );
  expect(button("Więcej: Miasto")).toBeEnabled();
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

test("removing a place asks first, then takes it out with every reference to it", async () => {
  view();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Usuń: miejsce „Studio Kortowo”",
    }),
  );
  const question = await screen.findByRole("alertdialog", {
    name: "Usunąć miejsce „Studio Kortowo” z notatek?",
  });
  expect(
    within(question).getByText(
      "Znikną też godziny pracy w tym miejscu i jego przypisanie do usług. W koncie firmy nic się nie zmieni.",
    ),
  ).toBeInTheDocument();

  // „Anuluj” leaves the notes as they are.
  fireEvent.click(within(question).getByRole("button", { name: "Anuluj" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.changeAssistantProfile).not.toHaveBeenCalled();

  const without = {
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
  };
  api.getAssistantSetup.mockResolvedValue(setupWith(without));
  fireEvent.click(button("Usuń: miejsce „Studio Kortowo”"));
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", {
      name: "Usuń z notatek",
    }),
  );

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      without,
      7,
      expect.any(String),
    ),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Usunięto z notatek: miejsce „Studio Kortowo”.",
  );
  expect(screen.queryByRole("heading", { name: "Studio Kortowo" })).toBeNull();
  // What follows is the account's place, which has no control: the group's
  // heading takes the focus.
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Miejsca" })).toHaveFocus(),
  );
});

test("after a removed entry the focus goes to the next one's first control, or up to the heading", async () => {
  view();

  // The next place can be removed too: its button is the first control.
  api.getAssistantSetup.mockResolvedValue(
    setupWith({ places: [STUDIO, OFFICE] }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Usuń: miejsce „Salon na Mazurskiej”",
    }),
  );
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", {
      name: "Usuń z notatek",
    }),
  );
  await waitFor(() =>
    expect(button("Usuń: miejsce „Studio Kortowo”")).toHaveFocus(),
  );

  // The only person: the group goes with her, the section's heading is left.
  api.getAssistantSetup.mockResolvedValue(
    setupWith({ places: [STUDIO, OFFICE], people: [] }),
  );
  fireEvent.click(button("Usuń: osoba „Ania”"));
  const question = await screen.findByRole("alertdialog", {
    name: "Usunąć osobę „Ania” z notatek?",
  });
  expect(
    within(question).getByText(
      "Zniknie też jej przypisanie do usług. W koncie firmy nic się nie zmieni.",
    ),
  ).toBeInTheDocument();
  fireEvent.click(
    within(question).getByRole("button", { name: "Usuń z notatek" }),
  );
  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenLastCalledWith(
      {
        places: [STUDIO, OFFICE],
        people: [],
        offers: [{ ...CUT, people: said([]) }, COLOUR],
      },
      7,
      expect.any(String),
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Co już wiadomo" }),
    ).toHaveFocus(),
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Usunięto z notatek: osoba „Ania”.",
  );
});

test("„Usuń” on a value removes the field at once; the focus goes to the next row", async () => {
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  api.getAssistantSetup.mockResolvedValue(
    setupWith({
      company: { name: COMPANY.name, category: COMPANY.category },
    }),
  );
  await choose("Więcej: Miasto", "Usuń");

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      { company: { city: null } },
      7,
      expect.any(String),
    ),
  );
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Usunięto z notatek: Miasto.",
  );
  await waitFor(() => expect(button("Więcej: Kategoria")).toHaveFocus());

  // The last value of a place: nothing follows, so the group's heading.
  api.getAssistantSetup.mockResolvedValue(
    setupWith({ places: [SALON, { key: "studio" }, OFFICE] }),
  );
  await choose("Więcej: Nazwa — Studio Kortowo", "Usuń");
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Miejsca" })).toHaveFocus(),
  );
  expect(
    screen.getByRole("heading", { name: "Bez nazwy" }),
  ).toBeInTheDocument();
});

test("„Popraw” saves the typed text as the owner's confirmed value; an empty one is not saved", async () => {
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  await choose("Więcej: Miasto", "Popraw");
  const input = await screen.findByLabelText("Miasto");
  expect(input).toHaveValue("Olsztyn");
  expect(input).toHaveFocus();

  fireEvent.change(input, { target: { value: "  " } });
  expect(button("Zapisz")).toBeDisabled();
  fireEvent.submit(input);
  expect(api.changeAssistantProfile).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: " Ostróda " } });
  fireEvent.click(button("Zapisz"));

  await waitFor(() =>
    expect(api.changeAssistantProfile).toHaveBeenCalledWith(
      { company: { city: said("Ostróda", "owner", true) } },
      7,
      expect.any(String),
    ),
  );
  // Saved: the input closes and the focus is back on the row's „…”.
  await waitFor(() => expect(screen.queryByLabelText("Miasto")).toBeNull());
  await waitFor(() => expect(button("Więcej: Miasto")).toHaveFocus());
  expect(screen.getByRole("status")).toHaveTextContent("Zapisano w notatkach.");
});

test("„Popraw” takes a whole number for a duration, and „Anuluj” leaves the value alone", async () => {
  view();
  const name = "Czas trwania — Strzyżenie damskie";

  await screen.findByText("Salon Fryzjerski Ania");
  await choose(`Więcej: ${name}`, "Popraw");
  fireEvent.change(await screen.findByLabelText(name), {
    target: { value: "1,5" },
  });
  expect(button("Zapisz")).toBeDisabled();
  fireEvent.click(button("Anuluj"));
  expect(screen.queryByLabelText(name)).toBeNull();
  expect(api.changeAssistantProfile).not.toHaveBeenCalled();
  await waitFor(() => expect(button(`Więcej: ${name}`)).toHaveFocus());

  await choose(`Więcej: ${name}`, "Popraw");
  expect(await screen.findByLabelText(name)).toHaveValue("45");
  fireEvent.change(screen.getByLabelText(name), { target: { value: "60" } });
  fireEvent.click(button("Zapisz"));

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

test("notes changed in the meantime are read again and the person is told", async () => {
  api.changeAssistantProfile.mockRejectedValue(
    problem("assistant_profile_version_conflict", 409),
  );
  view();

  await screen.findByText("Salon Fryzjerski Ania");
  api.getAssistantSetup.mockResolvedValue({
    ...setupWith({
      company: { name: said("Salon Ania"), city: said("Ostróda") },
    }),
    version: 8,
  });
  await choose("Więcej: Miasto", "Usuń");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Notatki o firmie zmieniły się w międzyczasie. Sprawdź je i spróbuj ponownie.",
  );
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(2);
  expect(row("Miasto").getByText("Ostróda")).toBeInTheDocument();
  expect(screen.getByRole("status")).toBeEmptyDOMElement();

  // The next change names the version now shown.
  api.changeAssistantProfile.mockResolvedValue({});
  await choose("Więcej: Miasto", "Usuń");
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

  await screen.findByText("Salon Fryzjerski Ania");
  await choose("More: City", "Remove");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The change could not be saved. Try again.",
  );
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(1);
  expect(row("City").getByText("Olsztyn")).toBeInTheDocument();
});

test("beside the conversation the notes are as tall as the room under them", async () => {
  // jsdom has no layout: the block says where it sits, as a browser would.
  let top = 210;
  const rect = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(() => ({ top }) as DOMRect);
  const height = vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
  try {
    view();
    const title = await screen.findByText(
      "Notatki o firmie — co już wiadomo i czego brakuje",
    );
    const block = title.parentElement as HTMLElement;

    // In its place in the page, 210 px down: whole in the window, 16 px clear.
    expect(block.style.maxHeight).toBe("574px");
    // The page scrolled and the block sticks under the panel's header.
    top = 84;
    fireEvent.scroll(window);
    expect(block.style.maxHeight).toBe("700px");
  } finally {
    rect.mockRestore();
    height.mockRestore();
  }
});

test("the notes are read again when the conversation settles", async () => {
  const page = view();

  await screen.findByText("Salon Fryzjerski Ania");
  page.settle(1);

  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(2));
});

test("notes that could not be read offer to try again", async () => {
  api.getAssistantSetup.mockRejectedValueOnce(new Error("offline"));
  view();

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Nie udało się wczytać notatek o firmie.");
  expect(screen.queryByText("Wczytywanie notatek o firmie…")).toBeNull();

  fireEvent.click(
    within(alert).getByRole("button", { name: "Spróbuj ponownie" }),
  );

  expect(await screen.findByText("Salon Fryzjerski Ania")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(2);
});

/** A stay whose units and price are on their way: asked, ready and waiting. */
const STAY: AssistantSetup = {
  version: 4,
  document: {
    schema: "company-profile.v1",
    offers: [
      {
        key: "domki",
        name: said("Domki"),
        units: said(3),
        price: said({ amount: "450.00", currency: "PLN", per: "night" }),
        vat: said("8"),
      },
      { key: "kajak", name: said("Kajak") },
    ],
  },
  labels: { categories: {}, presets: {} },
  questions: [
    {
      field: "offers.kajak.units",
      kind: "ask",
      reason: "offer_needs_units",
      proposal: null,
      options: [],
    },
    {
      field: "offers.kajak.price",
      kind: "ask",
      reason: "offer_needs_price",
      proposal: null,
      options: [],
    },
    {
      field: "offers.kajak.vat",
      kind: "ask",
      reason: "price_needs_vat",
      proposal: null,
      options: [],
    },
  ],
  ready: [
    {
      ref: "units:domki",
      title: { pl: "Ustaw jednostki usługi", en: "Set a service's units" },
      risk: "draft",
    },
    {
      ref: "price:domki",
      title: { pl: "Zapisz cenę", en: "Save a price" },
      risk: "draft",
    },
  ],
  waiting: [
    { ref: "units:kajak", reason: "waits", waits_for: ["offer:kajak"] },
    { ref: "price:kajak", reason: "waits", waits_for: ["offer:kajak"] },
  ],
  unsupported: [
    { field: "offers.kajak.price", code: "price_currency", detail: "PLN" },
  ],
};

test("a stay's units, its price and the tax rate are said in words: asked, ready and waiting", async () => {
  api.getAssistantSetup.mockResolvedValue(STAY);
  view();

  await screen.findByRole("heading", { name: "Domki" });
  const domki = entry("Domki");
  expect(row("Liczba jednostek", domki).getByText("3")).toBeInTheDocument();
  expect(row("Cena", domki).getByText("450,00 zł za noc")).toBeInTheDocument();
  // The rate is a code in the notes and words on the screen.
  expect(row("Stawka VAT", domki).getByText("8%")).toBeInTheDocument();
  for (const line of [
    "Ile jednostek — domków, pokoi, sztuk sprzętu — ma usługa „Kajak”?",
    "Ile kosztuje usługa „Kajak” i za co jest ta cena?",
    "Jaka stawka VAT dotyczy ceny usługi „Kajak”?",
    "Ustaw jednostki usługi: Domki",
    "Zapisz cenę: Domki",
    "W kolejnym kroku: jednostki usługi „Kajak”. Najpierw: usługa „Kajak”.",
    "W kolejnym kroku: cena usługi „Kajak”. Najpierw: usługa „Kajak”.",
    "Cena usługi „Kajak”: cennik firmy jest w walucie PLN. Podaj cenę w tej walucie — kwot nie przeliczamy.",
  ]) {
    expect(screen.getByText(line)).toBeInTheDocument();
  }
  // A step's kind and an offer's key stay out of sight.
  expect(document.body.textContent).not.toMatch(
    /units:|price:|offer_needs|domki\b/,
  );
});
