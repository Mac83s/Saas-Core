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

import type {
  CatalogDictionary,
  CatalogItem,
  CatalogPage,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CatalogSearch } from "./catalog-search";

const api = vi.hoisted(() => ({
  readCatalogDictionary: vi.fn(),
  searchCatalog: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const DICTIONARY: CatalogDictionary = {
  cities: [
    { slug: "olsztyn", name: "Olsztyn", voivodeship: "warmińsko-mazurskie" },
  ],
  categories: [],
};

function item(
  slug: string,
  name: string,
  distance: number | null = null,
): CatalogItem {
  return {
    slug,
    city_slug: "olsztyn",
    city: "Olsztyn",
    category: "uroda-i-zdrowie",
    display_name: name,
    headline: "",
    photo_id: null,
    url: `/katalog/olsztyn/${slug}/`,
    is_external: false,
    distance_km: distance,
  };
}

function page(items: CatalogItem[], similar: CatalogItem[] = []): CatalogPage {
  return { total: items.length, page: 1, page_size: 20, items, similar };
}

function view(ui: ReactNode, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      {ui}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.readCatalogDictionary.mockResolvedValue(DICTIONARY);
  api.searchCatalog.mockResolvedValue(page([]));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("nothing exact: the meaning-based entries come as similar ones", async () => {
  api.searchCatalog.mockResolvedValue(
    page([], [item("gabinet-usmiech", "Gabinet Uśmiech")]),
  );
  const { container } = view(<CatalogSearch locale="pl" />);

  fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj" }), {
    target: { value: "boli mnie ząb" },
  });

  expect(
    await screen.findByRole("heading", {
      name: "Nie znaleźliśmy dokładnie „boli mnie ząb”. Podobne:",
    }),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "Gabinet Uśmiech" })).toBeTruthy();
  // Typing pauses before the catalogue is asked: one search per pause.
  expect(api.searchCatalog).toHaveBeenLastCalledWith(
    expect.objectContaining({ q: "boli mnie ząb" }),
  );
  expect((await axe.run(container)).violations).toEqual([]);
});

test("exact entries first, the similar ones under “may also”, in en too", async () => {
  api.searchCatalog.mockResolvedValue(
    page(
      [item("stomatolog", "Stomatolog Nowak")],
      [item("ortodonta", "Ortodonta Kos")],
    ),
  );
  view(<CatalogSearch locale="en" />, "en");

  expect(
    await screen.findByRole("link", { name: "Stomatolog Nowak" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "You might also consider" }),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "Ortodonta Kos" })).toBeTruthy();
});

test("a radius around the town is asked for and the distance shown", async () => {
  api.searchCatalog.mockResolvedValue(
    page([item("salon", "Salon Anna", 54.6)]),
  );
  view(<CatalogSearch initialCity="olsztyn" locale="pl" />);

  const slider = await screen.findByLabelText("Odległość");
  expect(screen.getByText("Tylko to miasto")).toBeTruthy();
  fireEvent.keyDown(slider, { key: "ArrowRight" });

  await waitFor(() =>
    expect(api.searchCatalog).toHaveBeenLastCalledWith(
      expect.objectContaining({ city: "olsztyn", radius_km: 5 }),
    ),
  );
  expect(screen.getByText("Do 5 km")).toBeTruthy();
  expect(await screen.findByText(/55 km/)).toBeTruthy();
});

test("near me sends the point with a radius and can be turned off", async () => {
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (success: PositionCallback) =>
        success({
          coords: { latitude: 53.78, longitude: 20.48 },
        } as GeolocationPosition),
    },
  });
  view(<CatalogSearch locale="pl" />);

  fireEvent.click(await screen.findByRole("button", { name: "Blisko mnie" }));

  await waitFor(() =>
    expect(api.searchCatalog).toHaveBeenLastCalledWith(
      expect.objectContaining({ lat: 53.78, lng: 20.48, radius_km: 25 }),
    ),
  );
  expect(screen.getByText("Blisko Ciebie")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Wyłącz „Blisko mnie”" }));
  await waitFor(() =>
    expect(api.searchCatalog).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ lat: 53.78 }),
    ),
  );
});

test("a refused location says so and leaves the town select", async () => {
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: {
      getCurrentPosition: (
        _success: PositionCallback,
        failure: PositionErrorCallback,
      ) => failure({ code: 1 } as GeolocationPositionError),
    },
  });
  view(<CatalogSearch locale="pl" />);

  fireEvent.click(await screen.findByRole("button", { name: "Blisko mnie" }));

  expect(
    await screen.findByText(
      "Nie udało się ustalić lokalizacji. Wybierz miasto.",
    ),
  ).toBeTruthy();
  expect(screen.getByRole("combobox", { name: "Miasto" })).toBeTruthy();
});
