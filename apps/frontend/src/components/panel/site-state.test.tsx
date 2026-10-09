import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../messages/en.json";
import polishMessages from "../../../messages/pl.json";
import { SiteState } from "./site-state";

const { api, slot } = vi.hoisted(() => ({
  api: {
    getPublicLocales: vi.fn(),
    listContentTypes: vi.fn(),
    // The builder's own lists: the card must ask for none of them.
    listSiteDomains: vi.fn(),
    listSitePages: vi.fn(),
    listSitePublications: vi.fn(),
    listSites: vi.fn(),
  },
  // Whether the product serves public pages of its own (ADR-080): in a
  // product's repository the slot declares some, here each test says.
  slot: { productSite: null as object | null },
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("#lib/product-site/site", () => ({
  get productSite() {
    return slot.productSite;
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const SITE = {
  id: "site-one",
  name: "Puppily",
  default_locale: "pl",
  // The builder site was published once: the card says nothing of it.
  current_publication_id: "publication-two",
};
const type = (
  name: string,
  entries: number,
  published: number,
  archived = false,
) => ({
  collection: { id: name, name, archived },
  entries,
  published,
  locales: ["pl"],
});

function renderState(
  messages: Record<string, unknown> = polishMessages,
  locale = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Europe/Warsaw"
    >
      <SiteState />
    </NextIntlClientProvider>,
  );
}

/** Every address a card could send the reader to. */
const hrefs = (container: HTMLElement) =>
  [...container.querySelectorAll("a")].map((link) => link.getAttribute("href"));
const facts = (container: HTMLElement) =>
  Object.fromEntries(
    [...container.querySelectorAll("dt")].map((term) => [
      term.textContent,
      term.nextElementSibling?.textContent,
    ]),
  );

beforeEach(() => {
  vi.clearAllMocks();
  slot.productSite = {};
  api.listSites.mockResolvedValue({ items: [SITE] });
  api.listContentTypes.mockResolvedValue({
    types: [
      type("Blog", 5, 3),
      type("Poradniki", 2, 1),
      // Switched off: it shows nothing to anybody, and is not counted.
      type("Archiwum", 7, 7, true),
    ],
  });
  api.getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en", "de"],
    offered: [
      { code: "pl", native_name: "Polski" },
      { code: "en", native_name: "English" },
      { code: "de", native_name: "Deutsch" },
    ],
  });
});

test("mówi, co platforma napisała i gdzie widać to, co opublikowano — bez słowa o podstronach, publikacji witryny i domenach", async () => {
  const { container } = renderState();

  expect(
    await screen.findByRole("heading", { level: 2, name: "Treści platformy" }),
  ).toBeInTheDocument();
  // The product's own host — the one the panel is on — and never the
  // builder site's: no host serves that one (ADR-079 pkt 29).
  expect(
    screen.getByText(
      `Opublikowane wpisy pokazuje serwis pod adresem ${window.location.host}.`,
    ),
  ).toBeInTheDocument();
  expect(facts(container)).toEqual({
    "Typy treści": "Blog, Poradniki",
    Wpisy: "7 wpisów4 opublikowane",
    Języki: "Polski, English, Deutsch",
  });
  // Nothing of the site builder: no state of a site, no pages, no
  // publication of a site, no domain — and nothing to open.
  for (const word of [
    "Opublikowana",
    "Zmiany nieopublikowane",
    "Jeszcze nieopublikowana",
    "Ostatnia publikacja",
    "Podstrony",
    "podstron",
    "domena",
    "Puppily",
  ])
    expect(container).not.toHaveTextContent(word);
  expect(hrefs(container)).toEqual([]);
  // It asks for what „Treści” asks for, and for none of the builder's lists.
  expect(api.listContentTypes).toHaveBeenCalledWith("site-one");
  expect(api.listSitePages).not.toHaveBeenCalled();
  expect(api.listSitePublications).not.toHaveBeenCalled();
  expect(api.listSiteDomains).not.toHaveBeenCalled();

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("bez typów i wpisów mówi to wprost", async () => {
  api.listContentTypes.mockResolvedValue({ types: [] });
  const { container } = renderState();

  expect(await screen.findByText("Nie założono")).toBeInTheDocument();
  expect(facts(container)).toEqual({
    "Typy treści": "Nie założono",
    Wpisy: "0 wpisów",
    Języki: "Polski, English, Deutsch",
  });
});

test("in English too; where the product has no public pages the card names no host at all", async () => {
  slot.productSite = null;
  api.listContentTypes.mockResolvedValue({ types: [type("Blog", 1, 1)] });
  const { container } = renderState(englishMessages, "en");

  expect(
    await screen.findByRole("heading", { level: 2, name: "Platform content" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Published entries are shown by the service's own pages. This service has none yet.",
    ),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent(window.location.host);
  expect(facts(container)).toEqual({
    "Content types": "Blog",
    Entries: "1 entry1 published",
    Languages: "Polski, English, Deutsch",
  });
});

test("bez miejsca na treści prowadzi do „Treści”, gdzie się je zakłada, i o nic więcej nie pyta", async () => {
  api.listSites.mockResolvedValue({ items: [] });
  const { container } = renderState();

  expect(
    await screen.findByRole("heading", {
      level: 2,
      name: "Nie ma tu jeszcze treści",
    }),
  ).toBeInTheDocument();
  // Not „Podstrony”: that address is gone from a publisher's panel.
  expect(screen.getByRole("link", { name: "Zacznij" })).toHaveAttribute(
    "href",
    "/panel/sites/content",
  );
  expect(hrefs(container)).toEqual(["/panel/sites/content"]);
  expect(api.listContentTypes).not.toHaveBeenCalled();
  expect(api.getPublicLocales).not.toHaveBeenCalled();
});

test("nieudany odczyt mówi o tym i daje ponowić", async () => {
  api.listContentTypes.mockRejectedValueOnce(new Error("offline"));
  renderState();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się wczytać stanu treści.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { level: 2, name: "Treści platformy" }),
    ).toBeInTheDocument(),
  );
});
