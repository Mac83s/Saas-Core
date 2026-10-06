import type { ReactNode } from "react";
import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import type {
  CatalogDictionary,
  CatalogState,
  OrganizationProfile,
  PublicProfileSummary,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CatalogSearch } from "./catalog-search";
import { ProfilePanel } from "./profile-panel";

const api = vi.hoisted(() => ({
  readOrganizationProfile: vi.fn(),
  readCatalogDictionary: vi.fn(),
  publishOrganizationProfile: vi.fn(),
  withdrawOrganizationProfile: vi.fn(),
  updateProfile: vi.fn(),
  searchCatalog: vi.fn(),
  // Where the company takes visits; none without the calendar.
  getBookingSetup: vi.fn(),
  // The card's other languages (TL12d): one language here, no engine.
  getProfileTranslations: vi.fn(async () => ({
    source_locale: "pl",
    languages: [],
  })),
  getTranslationOffer: vi.fn(async () => {
    throw new Error("not composed");
  }),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

vi.mock("#i18n/navigation", () => ({
  Link: ({ children, ...props }: { children: ReactNode; href: string }) => (
    <a {...props}>{children}</a>
  ),
}));

const DICTIONARY: CatalogDictionary = {
  cities: [
    { slug: "mragowo", name: "Mrągowo", voivodeship: "warmińsko-mazurskie" },
    { slug: "olsztyn", name: "Olsztyn", voivodeship: "warmińsko-mazurskie" },
  ],
  categories: [
    {
      key: "uroda-i-zdrowie",
      labels: { pl: "Uroda i zdrowie", en: "Beauty and health" },
    },
  ],
  locales: ["pl"],
};

function profile(
  overrides: Partial<PublicProfileSummary> = {},
): PublicProfileSummary {
  return {
    id: "019c5f87-fce8-739b-b960-b7a195bfc298",
    subject_kind: "organization",
    display_name: "Salon Uroda",
    headline: "Fryzjerstwo damsko-męskie",
    bio: "",
    photo_id: null,
    membership_id: null,
    contact_email: "",
    contact_phone: "",
    contact_address: "",
    links: [],
    languages: [],
    specializations: [],
    locale: "pl",
    city_slug: "mragowo",
    category: "uroda-i-zdrowie",
    layout: "card",
    version: 3,
    ...overrides,
  } as PublicProfileSummary;
}

function catalog(overrides: Partial<CatalogState> = {}): CatalogState {
  return {
    published: false,
    city_slug: "",
    slug: "",
    path: "",
    site_url: null,
    published_at: null,
    ...overrides,
  } as CatalogState;
}

function body(overrides: Partial<OrganizationProfile> = {}) {
  return { profile: profile(), catalog: catalog(), ...overrides };
}

function view(node: ReactNode, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      {node}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.readCatalogDictionary.mockResolvedValue(DICTIONARY);
  api.readOrganizationProfile.mockResolvedValue(body());
  api.getBookingSetup.mockRejectedValue(new Error("no calendar"));
  api.searchCatalog.mockResolvedValue({
    total: 0,
    page: 1,
    page_size: 20,
    items: [],
  });
});

afterEach(cleanup);

test("the business card screen offers publication and is accessible", async () => {
  const { container } = view(<ProfilePanel canManage />);

  // Off by default: nobody is listed without switching it on (ADR-053).
  const toggle = await screen.findByRole("switch", {
    name: "Pokazuj wizytówkę w katalogu",
  });
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  // The dictionary drives both fields, so a value outside it cannot be picked.
  expect(screen.getByRole("combobox", { name: "Miasto" })).toHaveValue(
    "Mrągowo, warmińsko-mazurskie",
  );
  // A company from a village is told what to pick and where its address goes.
  expect(
    screen.getByText(/Firma spoza miasta wybiera najbliższe/),
  ).toBeTruthy();
  expect(screen.getByRole("option", { name: "Uroda i zdrowie" })).toBeTruthy();
  // Who reads the card's public text for the search by meaning is said where
  // the card is switched on (docs/architecture/model-port.md).
  expect(
    screen.getByText(/Qwen3 Embedding, przez pośrednika OpenRouter \(USA/),
  ).toBeTruthy();

  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});

test("a town is found by typing its name, with or without Polish letters", async () => {
  // Every town of Poland is on the list (ADR-053 §7): nobody scrolls it.
  api.readCatalogDictionary.mockResolvedValue({
    ...DICTIONARY,
    cities: [
      ...DICTIONARY.cities,
      { slug: "lomianki", name: "Łomianki", voivodeship: "mazowieckie" },
      { slug: "lomza", name: "Łomża", voivodeship: "podlaskie" },
      { slug: "olsztyn-slaskie", name: "Olsztyn", voivodeship: "śląskie" },
      { slug: "wolsztyn", name: "Wolsztyn", voivodeship: "wielkopolskie" },
    ],
  });
  api.updateProfile.mockResolvedValue(
    profile({ city_slug: "lomza", version: 2 }),
  );
  view(<ProfilePanel canManage />);
  const town = await screen.findByRole("combobox", { name: "Miasto" });
  const offered = async () =>
    within(await screen.findByRole("listbox"))
      .getAllByRole("option")
      .map((option) => option.textContent);

  const type = (text: string) => {
    town.focus();
    fireEvent.change(town, { target: { value: text } });
    fireEvent.keyDown(town, { key: "ArrowDown" });
  };

  type("lomz");

  // Only the towns the letters name; each with its region beside it.
  expect(await offered()).toEqual(["Łomżapodlaskie"]);
  fireEvent.click(screen.getByRole("option", { name: /Łomża/ }));

  await waitFor(() => expect(api.updateProfile).toHaveBeenCalledOnce());
  expect(api.updateProfile.mock.calls[0]?.[1]).toMatchObject({
    city_slug: "lomza",
  });
  await waitFor(() => expect(town).toHaveValue("Łomża, podlaskie"));

  // Two towns of one name are told apart by the region; the letters begin a
  // name, so Wolsztyn is not offered for them.
  type("olsztyn");
  expect(await offered()).toEqual([
    "Olsztynwarmińsko-mazurskie",
    "Olsztynśląskie",
  ]);
  // The region typed after the name picks one of the two.
  type("olsztyn, śl");
  expect(await offered()).toEqual(["Olsztynśląskie"]);
});

test("switching the card on shows where the entry leads", async () => {
  api.publishOrganizationProfile.mockResolvedValue(
    body({
      catalog: catalog({
        published: true,
        city_slug: "mragowo",
        slug: "salon-uroda",
        path: "/katalog/mragowo/salon-uroda/",
      }),
    }),
  );

  view(<ProfilePanel canManage />);
  const toggle = await screen.findByRole("switch", {
    name: "Pokazuj wizytówkę w katalogu",
  });
  fireEvent.click(toggle);

  await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
  expect(api.publishOrganizationProfile).toHaveBeenCalledTimes(1);
  expect(screen.getByText("/katalog/mragowo/salon-uroda/")).toBeTruthy();
  expect(
    screen.getByText(
      "Wpis w katalogu prowadzi do strony wizytówki na naszej platformie.",
    ),
  ).toBeTruthy();
});

test("switching a listed card off withdraws it", async () => {
  const listed = catalog({
    published: true,
    city_slug: "mragowo",
    slug: "salon-uroda",
    path: "/katalog/mragowo/salon-uroda/",
  });
  api.readOrganizationProfile
    .mockResolvedValueOnce(body({ catalog: listed }))
    .mockResolvedValueOnce(body());

  view(<ProfilePanel canManage />);
  const toggle = await screen.findByRole("switch", {
    name: "Pokazuj wizytówkę w katalogu",
  });
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  fireEvent.click(toggle);

  await waitFor(() =>
    expect(toggle.getAttribute("aria-checked")).toBe("false"),
  );
  expect(api.withdrawOrganizationProfile).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("/katalog/mragowo/salon-uroda/")).toBeNull();
});

test("a company with a website is said to lead there instead", async () => {
  api.readOrganizationProfile.mockResolvedValue(
    body({
      catalog: catalog({
        published: true,
        city_slug: "mragowo",
        slug: "salon-uroda",
        path: "/katalog/mragowo/salon-uroda/",
        site_url: "https://salon-uroda.pl/",
      }),
    }),
  );

  view(<ProfilePanel canManage />);

  expect(
    await screen.findByText(
      "Wpis w katalogu prowadzi do Twojej strony internetowej.",
    ),
  ).toBeTruthy();
  expect(screen.getByText("https://salon-uroda.pl/")).toBeTruthy();
});

test("a refused publication shows the server's own sentence", async () => {
  api.publishOrganizationProfile.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Konflikt",
      status: 409,
      code: "profile_not_publishable",
      detail:
        "Uzupełnij nazwę, miasto i kategorię przed publikacją w katalogu.",
      correlation_id: null,
    }),
  );

  view(<ProfilePanel canManage />);
  const toggle = await screen.findByRole("switch", {
    name: "Pokazuj wizytówkę w katalogu",
  });
  fireEvent.click(toggle);

  expect(
    await screen.findByText(
      "Uzupełnij nazwę, miasto i kategorię przed publikacją w katalogu.",
    ),
  ).toBeTruthy();
});

test("a field saves on leaving it and says so; an untouched one asks nothing (UX-052)", async () => {
  api.updateProfile.mockResolvedValue(
    profile({ display_name: "Salon Uroda i Styl", version: 4 }),
  );
  view(<ProfilePanel canManage />);

  const name = await screen.findByLabelText("Nazwa w katalogu i na stronie");
  expect(
    screen.getByText("Zmiany zapisują się same, gdy wyjdziesz z pola."),
  ).toBeTruthy();
  fireEvent.blur(name);
  expect(api.updateProfile).not.toHaveBeenCalled();

  fireEvent.change(name, { target: { value: "Salon Uroda i Styl" } });
  fireEvent.blur(name);
  await waitFor(() => expect(api.updateProfile).toHaveBeenCalledOnce());
  expect(await screen.findByText("Zapisano")).toBeTruthy();
  // One sentence gets two lines and a count, not a clipped single line.
  expect(screen.getByText("25 / 200 znaków")).toBeTruthy();
});

test("the card offers the address of the place where visits happen (UX-053)", async () => {
  api.getBookingSetup.mockResolvedValue({
    locations: [
      {
        id: "p1",
        name: "Gabinet",
        address: "ul. Zdrowa 5, Warszawa",
        active: true,
      },
      { id: "p2", name: "Stary lokal", address: "ul. Dawna 1", active: false },
    ],
  });
  api.readOrganizationProfile.mockResolvedValue(
    body({ profile: profile({ contact_address: "ul. Testowa 3, Olsztyn" }) }),
  );
  api.updateProfile.mockResolvedValue(
    profile({ contact_address: "ul. Zdrowa 5, Warszawa", version: 4 }),
  );
  view(<ProfilePanel canManage />);

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Użyj adresu: Gabinet, ul. Zdrowa 5, Warszawa",
    }),
  );
  await waitFor(() =>
    expect(api.updateProfile.mock.calls[0]?.[1]).toMatchObject({
      contact_address: "ul. Zdrowa 5, Warszawa",
    }),
  );
  // The addresses agree now: nothing left to offer.
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /Użyj adresu/ })).toBeNull(),
  );
});

test("without the permission nothing on the card can be edited", async () => {
  view(<ProfilePanel canManage={false} />);

  const name = await screen.findByLabelText("Nazwa w katalogu i na stronie");

  expect((name as HTMLInputElement).disabled).toBe(true);
  expect(
    screen
      .getByRole("switch", { name: "Pokazuj wizytówkę w katalogu" })
      .getAttribute("aria-disabled"),
  ).toBe("true");
});

test("the public listing links out only for an entry that leaves the platform", async () => {
  api.searchCatalog.mockResolvedValue({
    total: 2,
    page: 1,
    page_size: 20,
    items: [
      {
        slug: "salon-uroda",
        city_slug: "mragowo",
        city: "Mrągowo",
        category: "uroda-i-zdrowie",
        display_name: "Salon Uroda",
        headline: "Fryzjerstwo",
        photo_id: null,
        url: "/katalog/mragowo/salon-uroda/",
        is_external: false,
      },
      {
        slug: "warsztat",
        city_slug: "mragowo",
        city: "Mrągowo",
        category: "motoryzacja",
        display_name: "Warsztat Kowalski",
        headline: "Mechanika",
        photo_id: null,
        url: "https://warsztat.pl/",
        is_external: true,
      },
    ],
  });

  view(<CatalogSearch locale="pl" />);

  const own = await screen.findByRole("link", { name: "Salon Uroda" });
  const external = screen.getByRole("link", { name: /Warsztat Kowalski/ });

  expect(own.getAttribute("target")).toBe(null);
  expect(external.getAttribute("target")).toBe("_blank");
  expect(external.getAttribute("rel")).toBe("noreferrer");
});

test("the listing says so when a town has nobody yet, in en too", async () => {
  view(<CatalogSearch locale="en" />, "en");

  await waitFor(() => {
    expect(
      screen.getByText("Nothing found. Try another city or category."),
    ).toBeTruthy();
  });
});
