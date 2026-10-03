import axe from "axe-core";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type SeoPreview as Preview,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SeoPreview } from "./seo-preview";

const { api } = vi.hoisted(() => ({ api: { readSeoPreview: vi.fn() } }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const ORIGIN = "https://studio.example.test";
const SITE = "0199f0a0-0000-7000-8000-000000000001";
const PAGE = "0199f0a0-0000-7000-8000-000000000002";

function preview(overrides: Partial<Preview> = {}): Preview {
  return {
    site_id: SITE,
    page_id: PAGE,
    locale: "pl",
    public: true,
    reason: "",
    url: `${ORIGIN}/oferta/`,
    title: "Oferta",
    description: "Projektujemy wnętrza od pierwszej rozmowy do odbioru.",
    site_name: "Studio",
    noindex: false,
    hreflang: { pl: `${ORIGIN}/oferta/`, en: `${ORIGIN}/en/offer/` },
    x_default: `${ORIGIN}/oferta/`,
    social_title: "Oferta",
    social_description: "",
    image: null,
    structured_data: {
      "@context": "https://schema.org",
      "@graph": [
        { "@type": "WebSite" },
        { "@type": ["LocalBusiness", "Store"] },
        { "@type": "WebPage" },
      ],
    },
    ...overrides,
  };
}

function view(locale: "pl" | "en" = "pl", version = 1) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SeoPreview locale="pl" pageId={PAGE} siteId={SITE} version={version} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("shows the result as a search engine would, its languages and what the page describes", async () => {
  api.readSeoPreview.mockResolvedValue(preview());
  const { container } = view();

  const result = await screen.findByRole("group", {
    name: "Wynik wyszukiwania",
  });
  expect(result.getAttribute("lang")).toBe("pl");
  expect(result.textContent).toContain(`Studio · ${ORIGIN}/oferta/`);
  expect(result.textContent).toContain("Oferta");
  expect(result.textContent).toContain("Projektujemy wnętrza");
  expect(api.readSeoPreview).toHaveBeenCalledWith(SITE, PAGE, "pl");
  expect(
    screen.getByText(`· ${ORIGIN}/en/offer/`, { exact: false }),
  ).toBeTruthy();
  expect(
    screen.getByText("Strona opisuje: WebSite, LocalBusiness, Store, WebPage."),
  ).toBeTruthy();
  // Nothing to warn about: a short title, a description, an indexed page.
  expect(screen.queryByText(/Wyszukiwarka pokaże około/)).toBeNull();
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("says what a search engine will cut, miss or not show", async () => {
  const title =
    "Projektowanie wnętrz mieszkań, domów i biur w Krakowie i okolicach — Studio";
  api.readSeoPreview.mockResolvedValue(
    preview({ title, description: "", noindex: true }),
  );
  view();

  const result = await screen.findByRole("group", {
    name: "Wynik wyszukiwania",
  });
  expect(result.textContent).toContain(`${title.slice(0, 60).trimEnd()}…`);
  expect(
    screen.getByText(
      `Tytuł ma ${title.length} znaków. Wyszukiwarka pokaże około 60.`,
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "Strona nie ma opisu. Wyszukiwarka sama wybierze fragment tekstu.",
    ),
  ).toBeTruthy();
  expect(
    screen.getByText("Ta strona prosi wyszukiwarki, żeby jej nie pokazywały."),
  ).toBeTruthy();
});

test("a company's text is shown as text, never as markup", async () => {
  api.readSeoPreview.mockResolvedValue(
    preview({
      title: '<img src=x onerror="alert(1)">',
      site_name: "<b>Studio</b>",
    }),
  );
  const { container } = view();

  await screen.findByRole("group", { name: "Wynik wyszukiwania" });
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
  expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
});

test("a version that would not go out says why, in the reader's language", async () => {
  api.readSeoPreview.mockResolvedValue(
    preview({ public: false, reason: "withheld" }),
  );
  const first = view("en");
  expect(
    await screen.findByText(/waits to be refreshed: a fact changed/),
  ).toBeTruthy();
  expect(screen.queryByRole("group", { name: "Search result" })).toBeNull();
  first.unmount();

  // A reason this screen does not know yet still reads as a sentence.
  api.readSeoPreview.mockResolvedValue(
    preview({ public: false, reason: "media_unavailable" }),
  );
  view("en");
  expect(
    await screen.findByText(
      "This language version will not go out with the next publication.",
    ),
  ).toBeTruthy();
});

test("a site that cannot be published yet says so and offers another try; a new version reads again", async () => {
  api.readSeoPreview.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "site_publication_not_ready",
      detail: "Site nie ma kompletnego draftu i bazowych tłumaczeń.",
      correlation_id: null,
    }),
  );
  api.readSeoPreview.mockResolvedValue(preview());
  const shown = view();

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(polishMessages.Sites.notReady);
  screen.getByRole("button", { name: "Spróbuj ponownie" }).click();
  expect(
    await screen.findByRole("group", { name: "Wynik wyszukiwania" }),
  ).toBeTruthy();

  shown.rerender(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <SeoPreview locale="pl" pageId={PAGE} siteId={SITE} version={2} />
    </NextIntlClientProvider>,
  );
  await waitFor(() => expect(api.readSeoPreview).toHaveBeenCalledTimes(3));
});
