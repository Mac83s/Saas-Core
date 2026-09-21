import type { ReactNode } from "react";
import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
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

  expect(
    await screen.findByRole("button", { name: "Opublikuj w katalogu" }),
  ).toBeTruthy();
  // The dictionary drives the selects, so a value outside it cannot be picked.
  expect(screen.getByRole("option", { name: "Mrągowo" })).toBeTruthy();
  expect(screen.getByRole("option", { name: "Uroda i zdrowie" })).toBeTruthy();

  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});

test("publication swaps the button and shows where the entry leads", async () => {
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
  fireEvent.click(
    await screen.findByRole("button", { name: "Opublikuj w katalogu" }),
  );

  expect(
    await screen.findByRole("button", { name: "Wycofaj z katalogu" }),
  ).toBeTruthy();
  expect(screen.getByText("/katalog/mragowo/salon-uroda/")).toBeTruthy();
  expect(
    screen.getByText(
      "Wpis w katalogu prowadzi do strony wizytówki na naszej platformie.",
    ),
  ).toBeTruthy();
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
  fireEvent.click(
    await screen.findByRole("button", { name: "Opublikuj w katalogu" }),
  );

  expect(
    await screen.findByText(
      "Uzupełnij nazwę, miasto i kategorię przed publikacją w katalogu.",
    ),
  ).toBeTruthy();
});

test("without the permission nothing on the card can be edited", async () => {
  view(<ProfilePanel canManage={false} />);

  const name = await screen.findByLabelText("Nazwa firmy");

  expect((name as HTMLInputElement).disabled).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Opublikuj w katalogu",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
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
