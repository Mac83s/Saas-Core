import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type PageListItem } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SitePagesTable } from "./site-pages-table";

const {
  deleteSitePage,
  listPageIncomingLinks,
  listSitePages,
  restoreSitePage,
  setPageType,
} = vi.hoisted(() => ({
  deleteSitePage: vi.fn(),
  listPageIncomingLinks: vi.fn(),
  listSitePages: vi.fn(),
  restoreSitePage: vi.fn(),
  setPageType: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  deleteSitePage,
  listPageIncomingLinks,
  listSitePages,
  restoreSitePage,
  setPageType,
}));

const siteId = "019ff20d-a000-7000-8000-000000000001";

function listed(overrides: Partial<PageListItem>): PageListItem {
  return {
    id: "019ff20d-a000-7000-8000-000000000002",
    site_id: siteId,
    name: "Start",
    key: "start",
    version: 3,
    current_draft_id: null,
    current_draft_hash: null,
    page_type: "landing",
    automation_policy: "manual",
    draft_author: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-29T10:00:00Z",
    title: null,
    path: null,
    published_version: null,
    in_navigation: false,
    deleted_at: null,
    ...overrides,
  };
}

const home = listed({
  id: "019ff20d-a000-7000-8000-00000000000a",
  name: "Start",
  key: "start",
  page_type: "homepage",
  path: "/start/",
  version: 3,
  published_version: 3,
  in_navigation: true,
});
const offer = listed({
  id: "019ff20d-a000-7000-8000-00000000000b",
  name: "Oferta",
  key: "oferta",
  title: "Oferta gabinetu",
  path: "/oferta/",
  version: 5,
  published_version: 4,
  in_navigation: true,
});
const draft = listed({
  id: "019ff20d-a000-7000-8000-00000000000c",
  name: "Szkic",
  key: "szkic",
  path: "/szkic/",
});
const pages = [home, offer, draft];

const callbacks = {
  onEdit: vi.fn(),
  onPreview: vi.fn(),
  onChanged: vi.fn(),
};

function renderTable(
  locale: "pl" | "en" = "pl",
  items: PageListItem[] = pages,
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SitePagesTable
        defaultLocale="pl"
        loading={false}
        pages={items}
        publicBaseUrl="http://gabinet.business.localhost:8080"
        siteId={siteId}
        {...callbacks}
      />
    </NextIntlClientProvider>,
  );
}

function row(name: string) {
  return screen.getByRole("row", { name: new RegExp(name) });
}

beforeEach(() => {
  vi.clearAllMocks();
  callbacks.onChanged.mockResolvedValue(undefined);
  listPageIncomingLinks.mockResolvedValue([
    { page_id: home.id, name: "Start", links: 2 },
  ]);
  deleteSitePage.mockResolvedValue({
    page: { ...offer, deleted_at: "2026-09-30T10:00:00Z" },
    publication_id: "019ff20d-a000-7000-8000-0000000000f1",
    redirects: [{ from_path: "/oferta/", to_path: "/" }],
  });
  listSitePages.mockResolvedValue({
    items: [
      listed({
        id: "019ff20d-a000-7000-8000-00000000000d",
        name: "Cennik",
        path: "/cennik/",
        deleted_at: "2026-09-30T09:00:00Z",
      }),
    ],
    next_cursor: null,
  });
});

afterEach(cleanup);

test("lists what each page is, where it answers and what visitors see", async () => {
  const rendered = renderTable();

  expect(screen.getByRole("table", { name: "Podstrony witryny" })).toBeTruthy();
  expect(within(row("Start")).getByText("Opublikowana")).toBeTruthy();
  expect(within(row("Start")).getByText("/")).toBeTruthy();
  expect(
    within(row("Oferta")).getByText("Zmiany nieopublikowane"),
  ).toBeTruthy();
  expect(within(row("Oferta")).getByText("Oferta gabinetu")).toBeTruthy();
  expect(within(row("Szkic")).getByText("Nieopublikowana")).toBeTruthy();

  // Editing is always in sight; it opens the studio for that page.
  fireEvent.click(
    within(row("Oferta")).getByRole("button", { name: "Edytuj" }),
  );
  expect(callbacks.onEdit).toHaveBeenCalledWith(offer);

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("offers no deleting or moving for the home page and opens it at the root", async () => {
  renderTable();

  fireEvent.click(screen.getByRole("button", { name: "Działania: Start" }));
  expect(
    await screen.findByRole("menuitem", { name: "Otwórz na stronie" }),
  ).toHaveAttribute("href", "http://gabinet.business.localhost:8080/");
  expect(screen.queryByRole("menuitem", { name: "Usuń" })).toBeNull();
  expect(
    screen.queryByRole("menuitem", { name: "Ustaw jako główną" }),
  ).toBeNull();
  // It answers at the root whatever its slug, so there is no address to move.
  expect(screen.queryByRole("menuitem", { name: "Zmień adres" })).toBeNull();
});

test("the last page cannot be deleted either", async () => {
  renderTable("pl", [offer]);

  fireEvent.click(screen.getByRole("button", { name: "Działania: Oferta" }));
  expect(await screen.findByRole("menuitem", { name: "Podgląd" })).toBeTruthy();
  expect(screen.queryByRole("menuitem", { name: "Usuń" })).toBeNull();
});

test("deletes a published page, redirecting its address to the home page", async () => {
  renderTable();

  fireEvent.click(screen.getByRole("button", { name: "Działania: Oferta" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń" }));

  const dialog = await screen.findByRole("dialog", {
    name: "Usunąć podstronę „Oferta”?",
  });
  expect(within(dialog).getByText(/zniknie ze strony od razu/)).toBeTruthy();
  expect(within(dialog).getByText("Zniknie też z menu witryny.")).toBeTruthy();
  expect(await within(dialog).findByText("Start (2 linki)")).toBeTruthy();
  const target = within(dialog).getByLabelText(
    "Dokąd ma prowadzić adres /oferta/",
  ) as HTMLSelectElement;
  // Only published pages can take a redirect; the home page is the default.
  expect(target.value).toBe(home.id);
  expect([...target.options].map((option) => option.value)).toEqual([home.id]);

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Usuń podstronę" }),
  );

  await waitFor(() => expect(deleteSitePage).toHaveBeenCalledOnce());
  const [pageId, input, key] = deleteSitePage.mock.calls[0]!;
  expect(pageId).toBe(offer.id);
  expect(input).toEqual({ expected_version: 5, redirect_to_page_id: home.id });
  expect(key).toMatch(/^page-delete-/);
  expect(
    await screen.findByText(
      "Usunięto „Oferta”. Adres /oferta/ prowadzi teraz do /.",
    ),
  ).toBeTruthy();
  expect(callbacks.onChanged).toHaveBeenCalled();
});

test("an unpublished page goes without a redirect and says why it cannot", async () => {
  deleteSitePage.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "page_is_last",
      detail: "The site's last page cannot be deleted.",
      correlation_id: null,
    }),
  );
  listPageIncomingLinks.mockResolvedValueOnce([]);
  renderTable();

  fireEvent.click(screen.getByRole("button", { name: "Działania: Szkic" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń" }));
  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByText(
      "Żadna inna podstrona do niej nie linkuje.",
    ),
  ).toBeTruthy();
  expect(within(dialog).queryByRole("combobox")).toBeNull();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Usuń podstronę" }),
  );

  expect(
    await within(dialog).findByText(
      "To ostatnia podstrona witryny — nie można jej usunąć.",
    ),
  ).toBeTruthy();
  expect(deleteSitePage.mock.calls[0]?.[1]).toEqual({
    expected_version: 3,
    redirect_to_page_id: null,
  });
});

test("marks another page as the home page", async () => {
  setPageType.mockResolvedValue({ ...offer, page_type: "homepage" });
  renderTable();

  fireEvent.click(screen.getByRole("button", { name: "Działania: Oferta" }));
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Ustaw jako główną" }),
  );

  await waitFor(() =>
    expect(setPageType).toHaveBeenCalledWith(offer.id, "homepage"),
  );
  expect(await screen.findByText(/jest teraz stroną główną/)).toBeTruthy();
});

test("restores a deleted page and asks for a new address when its old one is taken", async () => {
  restoreSitePage
    .mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "Conflict",
        status: 409,
        code: "page_restore_slug_taken",
        detail: "Another page uses /cennik/.",
        correlation_id: null,
      }),
    )
    .mockResolvedValueOnce(listed({ name: "Cennik" }));
  const rendered = renderTable("en");

  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "deleted" },
  });
  expect(
    await screen.findByRole("table", { name: "Deleted site pages" }),
  ).toBeTruthy();
  expect(listSitePages).toHaveBeenCalledWith(siteId, "deleted");
  expect(await screen.findByText("/cennik/")).toBeTruthy();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  fireEvent.click(
    within(row("Cennik")).getByRole("button", { name: "Restore" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "A new address for “Cennik”",
  });
  const address = within(dialog).getByLabelText(
    "New address",
  ) as HTMLInputElement;
  expect(address.value).toBe("cennik-2");
  fireEvent.change(address, { target: { value: "cennik-2026" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Restore" }));

  await waitFor(() => expect(restoreSitePage).toHaveBeenCalledTimes(2));
  expect(restoreSitePage.mock.calls[1]?.[2]).toEqual({ pl: "cennik-2026" });
  // A new address is a new request, not a replay of the refused one.
  expect(restoreSitePage.mock.calls[1]?.[1]).not.toBe(
    restoreSitePage.mock.calls[0]?.[1],
  );
  expect(
    await screen.findByText(
      "“Cennik” is restored as unpublished. Publish the site to bring it back.",
    ),
  ).toBeTruthy();
});
