import axe from "axe-core";
import { render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type { SearchVisibilitySite } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SearchVisibility } from "./search-visibility";

const { api } = vi.hoisted(() => ({
  api: { readSearchVisibility: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const ORIGIN = "https://studio.example.test";

function site(
  overrides: Partial<SearchVisibilitySite> = {},
): SearchVisibilitySite {
  return {
    site_id: "0199f0a0-0000-7000-8000-000000000001",
    name: "Studio",
    origin: ORIGIN,
    sitemap_url: `${ORIGIN}/sitemap.xml`,
    robots_url: `${ORIGIN}/robots.txt`,
    languages: [
      {
        locale: "pl",
        name: "Polski",
        home_url: `${ORIGIN}/`,
        llms_url: `${ORIGIN}/llms.txt`,
      },
      {
        locale: "de",
        name: "Deutsch",
        home_url: null,
        llms_url: `${ORIGIN}/de/llms.txt`,
      },
    ],
    ...overrides,
  };
}

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SearchVisibility />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("lists each language's home and llms.txt, and the site's sitemap and robots.txt", async () => {
  api.readSearchVisibility.mockResolvedValue({ sites: [site()] });
  const { container } = view();

  expect(
    await screen.findByRole("heading", {
      name: "Widoczność w wyszukiwarkach i AI",
    }),
  ).toBeTruthy();
  const table = screen.getByRole("table", {
    name: "Adresy strony Studio w jej językach",
  });
  const [polish, german] = within(table).getAllByRole("row").slice(1);
  expect(
    within(polish!)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href")),
  ).toEqual([`${ORIGIN}/`, `${ORIGIN}/llms.txt`]);
  // A language with articles only: its llms.txt, and a word instead of a
  // home address that would give 404.
  expect(
    within(german!)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href")),
  ).toEqual([`${ORIGIN}/de/llms.txt`]);
  expect(
    within(german!).getByText("Strona główna nie ma wersji w tym języku"),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: `${ORIGIN}/sitemap.xml` }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: `${ORIGIN}/robots.txt` }),
  ).toBeTruthy();
  // One site: its name is in the table's caption, not a heading of its own.
  expect(screen.queryByRole("heading", { name: "Studio" })).toBeNull();
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("names each site when the company has more than one, in English too", async () => {
  api.readSearchVisibility.mockResolvedValue({
    sites: [
      site(),
      site({ site_id: "0199f0a0-0000-7000-8000-000000000002", name: "Blog" }),
    ],
  });
  view("en");

  expect(
    await screen.findByRole("heading", {
      name: "Visibility in search engines and AI",
    }),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Studio" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Blog" })).toBeTruthy();
  expect(
    screen.getByRole("table", {
      name: "Addresses of the site Blog in its languages",
    }),
  ).toBeTruthy();
});

test("shows nothing for a company with no published site, and nothing when the read fails", async () => {
  api.readSearchVisibility.mockResolvedValue({
    sites: [
      site({
        origin: null,
        sitemap_url: null,
        robots_url: null,
        languages: [],
      }),
    ],
  });
  const unpublished = view();
  await waitFor(() => expect(api.readSearchVisibility).toHaveBeenCalledOnce());
  expect(unpublished.container.textContent).toBe("");
  unpublished.unmount();

  api.readSearchVisibility.mockRejectedValue(new Error("403"));
  const refused = view();
  await waitFor(() =>
    expect(api.readSearchVisibility).toHaveBeenCalledTimes(2),
  );
  expect(refused.container.textContent).toBe("");
});
