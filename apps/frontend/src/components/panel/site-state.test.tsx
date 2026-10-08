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
    listContentCollections: vi.fn(),
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
  current_publication_id: "publication-two",
};
const page = (version: number, published: number | null) => ({
  id: `page-${version}-${published}`,
  version,
  published_version: published,
});
const domain = (hostname: string, kind: string, status: string) => ({
  hostname,
  kind,
  status,
  is_canonical: kind === "custom" && status === "verified",
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

beforeEach(() => {
  vi.clearAllMocks();
  slot.productSite = {};
  api.listSites.mockResolvedValue({ items: [SITE] });
  api.listSitePages.mockResolvedValue({
    items: [page(3, 3), page(2, 2), page(5, 4), page(1, null)],
  });
  api.listSiteDomains.mockResolvedValue({
    items: [
      domain("puppily.app.example", "platform", "verified"),
      domain("puppily.example", "custom", "verified"),
    ],
  });
  api.listSitePublications.mockResolvedValue({
    items: [
      { id: "publication-two", created_at: "2026-10-07T12:30:00Z" },
      { id: "publication-one", created_at: "2026-10-01T08:00:00Z" },
    ],
  });
  api.listContentCollections.mockResolvedValue([{ id: "blog", name: "Blog" }]);
  api.getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en", "de"],
    offered: [
      { code: "pl", native_name: "Polski" },
      { code: "en", native_name: "English" },
      { code: "de", native_name: "Deutsch" },
    ],
  });
});

test("mówi, w jakim stanie jest strona, słowami „Podstron”, i gdzie widać to, co opublikowano", async () => {
  const { container } = renderState();

  expect(
    await screen.findByRole("heading", { level: 2, name: "Puppily" }),
  ).toBeInTheDocument();
  // Published, with two pages whose saved content readers do not see yet.
  expect(screen.getByText("Zmiany nieopublikowane")).toBeInTheDocument();
  // The product's own host — the one the panel is on — and never the
  // builder site's: no host serves that one (ADR-079 pkt 29).
  expect(
    screen.getByText(
      `Opublikowane wpisy pokazuje serwis pod adresem ${window.location.host}.`,
    ),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent("puppily.example");
  expect(container).not.toHaveTextContent("puppily.app.example");
  const facts = Object.fromEntries(
    [...container.querySelectorAll("dt")].map((term) => [
      term.textContent,
      term.nextElementSibling?.textContent,
    ]),
  );
  expect(facts).toEqual({
    "Ostatnia publikacja": "7 paź 2026, 14:30",
    Podstrony: "4 podstrony2 czekają na publikację",
    Blog: "Blog",
    Języki: "Polski, English, Deutsch",
  });
  // Published, and still nothing to open: the card links nowhere.
  expect(
    screen.queryByRole("link", { name: "Otwórz opublikowaną stronę" }),
  ).not.toBeInTheDocument();
  expect(hrefs(container)).toEqual([]);
  // Nothing here waits for DNS.
  expect(screen.queryByText(/Własna domena/)).not.toBeInTheDocument();

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("strona bez publikacji: „Jeszcze nieopublikowana”, bez odnośnika do strony, z domeną, która czeka", async () => {
  api.listSites.mockResolvedValue({
    items: [{ ...SITE, current_publication_id: null }],
  });
  api.listSitePages.mockResolvedValue({ items: [] });
  api.listSitePublications.mockResolvedValue({ items: [] });
  api.listContentCollections.mockResolvedValue([]);
  api.listSiteDomains.mockResolvedValue({
    items: [
      domain("puppily.app.example", "platform", "verified"),
      domain("puppily.example", "custom", "pending"),
    ],
  });
  const { container } = renderState();

  expect(
    await screen.findByText("Jeszcze nieopublikowana"),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent("puppily.app.example");
  expect(screen.getByText("Jeszcze nie publikowano")).toBeInTheDocument();
  expect(screen.getByText("0 podstron")).toBeInTheDocument();
  expect(screen.getByText("Nie założono")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Otwórz opublikowaną stronę" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Własna domena puppily\.example czeka na weryfikację\./),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Otwórz „Adres i domeny”" }),
  ).toHaveAttribute("href", "/panel/sites/address");
  // The one link of the card stays inside the panel.
  expect(hrefs(container)).toEqual(["/panel/sites/address"]);

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("everything published reads “Published”, in English too; a failed DNS check is named", async () => {
  api.listSitePages.mockResolvedValue({ items: [page(3, 3)] });
  api.listSiteDomains.mockResolvedValue({
    items: [
      domain("puppily.app.example", "platform", "verified"),
      domain("puppily.example", "custom", "failed"),
    ],
  });
  renderState(englishMessages, "en");

  expect(await screen.findByText("Published")).toBeInTheDocument();
  expect(screen.getByText("1 page")).toBeInTheDocument();
  expect(screen.queryByText(/wait for publication/)).not.toBeInTheDocument();
  expect(
    screen.getByText(
      /Your own domain puppily\.example did not pass the DNS check\./,
    ),
  ).toBeInTheDocument();
});

test("where the product has no public pages the card names no host at all", async () => {
  slot.productSite = null;
  const { container } = renderState(englishMessages, "en");

  expect(
    await screen.findByText(
      "This site has no address of its own. Published entries are shown by the service's own pages.",
    ),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent(window.location.host);
  expect(container).not.toHaveTextContent("puppily.example");
  expect(
    screen.queryByRole("link", { name: "Open published website" }),
  ).not.toBeInTheDocument();
});

test("bez strony prowadzi do jej założenia i o nic więcej nie pyta", async () => {
  api.listSites.mockResolvedValue({ items: [] });
  renderState();

  expect(
    await screen.findByRole("heading", {
      level: 2,
      name: "Strona jeszcze nie istnieje",
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Utwórz stronę" })).toHaveAttribute(
    "href",
    "/panel/sites",
  );
  expect(api.listSitePages).not.toHaveBeenCalled();
  expect(api.getPublicLocales).not.toHaveBeenCalled();
});

test("nieudany odczyt mówi o tym i daje ponowić", async () => {
  api.listSiteDomains.mockRejectedValueOnce(new Error("offline"));
  renderState();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się wczytać stanu strony.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { level: 2, name: "Puppily" }),
    ).toBeInTheDocument(),
  );
});
