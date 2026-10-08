import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { BlogPanel } from "./blog-panel";

/** The blog screen as one content type's entries (ADR-079 pkt 25,
 *  `/panel/sites/content/<typ>`), and what the blog screen itself does with
 *  a type that is switched off. The blog screen's own behaviour is
 *  `blog-panel.test.tsx`, unchanged by content types. */

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const {
  getPublicLocales,
  listContentCollections,
  listContentEntries,
  previewEntryRemoval,
  removeContentEntry,
  withdrawContentEntry,
} = vi.hoisted(() => ({
  getPublicLocales: vi.fn(),
  listContentCollections: vi.fn(),
  listContentEntries: vi.fn(),
  previewEntryRemoval: vi.fn(),
  removeContentEntry: vi.fn(),
  withdrawContentEntry: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getPublicLocales,
  listContentCollections,
  listContentEntries,
  previewEntryRemoval,
  removeContentEntry,
  withdrawContentEntry,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const blog = {
  id: "019ff20d-a000-7000-8000-000000000020",
  site_id: siteId,
  key: "blog",
  name: "Blog",
  kind: "blog",
  base_path: "blog",
  locale_paths: {},
  paths: { pl: "/blog/" },
  automation_policy: "manual",
  show_in_navigation: false,
  schema_type: "BlogPosting",
  in_site_feed: true,
  archived: false,
  archived_at: null,
};
const projects = {
  ...blog,
  id: "019ff20d-a000-7000-8000-000000000021",
  key: "realizacje",
  name: "Realizacje",
  base_path: "realizacje",
  paths: { pl: "/realizacje/" },
};
const off = {
  ...blog,
  id: "019ff20d-a000-7000-8000-000000000022",
  key: "aktualnosci",
  name: "Aktualności",
  base_path: "aktualnosci",
  paths: { pl: "/aktualnosci/" },
  archived: true,
  archived_at: "2026-10-08T10:00:00Z",
};

const entry = {
  id: "entry",
  collection_id: off.id,
  slug: "wpis",
  locale: "pl",
  title: "Wpis",
  excerpt: "",
  author_name: "",
  state: "draft",
  version: 1,
  published_at: null,
  publication_id: null,
  noindex: false,
  draft_author: null,
  translation_group: "019ff20d-a000-7000-8000-000000000040",
  schedule_state: "none",
  scheduled_publish_at: null,
  schedule_error: "",
  tags: [],
  categories: [],
  translation_of: null,
  pending_reason: "",
};

function renderPanel(typeId?: string, onLoaded = vi.fn()) {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <BlogPanel onLoaded={onLoaded} siteId={siteId} typeId={typeId} />
    </NextIntlClientProvider>,
  );
  return onLoaded;
}

beforeEach(() => {
  vi.clearAllMocks();
  listContentCollections.mockResolvedValue([blog, projects, off]);
  listContentEntries.mockResolvedValue({ items: [], next_cursor: null });
  getPublicLocales.mockRejectedValue(new Error("not asked here"));
});

test("shows one type's entries, with what the type is left to its settings", async () => {
  const onLoaded = renderPanel(projects.id);

  expect(
    await screen.findByText("Wpisy dostępne pod adresem /realizacje/."),
  ).not.toBeNull();
  await waitFor(() =>
    expect(listContentEntries).toHaveBeenCalledWith(projects.id),
  );
  expect(onLoaded).toHaveBeenCalledWith(projects);
  // No choice of section, no address, menu or automation here.
  expect(screen.queryByLabelText("Wybierz kolekcję")).toBeNull();
  expect(screen.queryByText("Pokaż blog w menu witryny")).toBeNull();
  expect(screen.queryByLabelText("Adres bloga")).toBeNull();
  expect(screen.getByRole("link", { name: "Ustawienia typu" })).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${projects.id}/settings?site=${siteId}`,
    ),
  );
  expect(screen.getByRole("button", { name: "Dodaj wpis" })).not.toBeNull();
});

test("a switched-off type takes no work but a withdrawal, and says where to switch it on", async () => {
  listContentEntries.mockResolvedValue({
    items: [
      { ...entry, id: "out", title: "Wpis na stronie", state: "published" },
      { ...entry, id: "draft", title: "Szkic wpisu", state: "draft" },
    ],
    next_cursor: null,
  });
  withdrawContentEntry.mockResolvedValue({ ...entry, id: "out" });
  renderPanel(off.id);

  expect(
    await screen.findByText(/Ten typ treści jest wyłączony/),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Dodaj wpis" })).toBeNull();
  expect(
    screen.getByRole("link", { name: "Wszystkie typy treści" }),
  ).not.toBeNull();
  // Its entries are listed; the one that is out can be withdrawn, so that
  // it does not come back with the type. Nothing is edited or published.
  expect(await screen.findByText("Szkic wpisu")).not.toBeNull();
  expect(screen.queryByRole("button", { name: /Edytuj/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Opublikuj/ })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Wycofaj wpis Wpis na stronie" }),
  );
  await waitFor(() => expect(withdrawContentEntry).toHaveBeenCalledWith("out"));
});

test("a type that is not there says so instead of offering a new blog", async () => {
  renderPanel("019ff20d-a000-7000-8000-0000000000ff");

  expect(
    await screen.findByText("Tego typu treści nie ma — mógł zostać usunięty."),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Załóż blog" })).toBeNull();
});

test("the blog screen offers the sections that are on, never one switched off", async () => {
  renderPanel();

  const picker = (await screen.findByLabelText(
    "Wybierz kolekcję",
  )) as HTMLSelectElement;
  expect([...picker.options].map((option) => option.textContent)).toEqual([
    "Blog",
    "Realizacje",
  ]);
});

test("leads to the type's categories and tags, on its page and on the plain blog screen", async () => {
  renderPanel(projects.id);
  await screen.findByText("Wpisy dostępne pod adresem /realizacje/.");
  expect(screen.getByRole("link", { name: "Kategorie" })).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${projects.id}/categories?site=${siteId}`,
    ),
  );
  expect(screen.getByRole("link", { name: "Tagi" })).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${projects.id}/tags?site=${siteId}`,
    ),
  );
});

test("the plain blog screen leads to the categories of the blog it shows", async () => {
  renderPanel();
  await screen.findByLabelText("Wybierz kolekcję");
  expect(screen.getByRole("link", { name: "Kategorie" })).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${blog.id}/categories?site=${siteId}`,
    ),
  );
  expect(screen.queryByRole("link", { name: "Ustawienia typu" })).toBeNull();
});

test("an entry of a switched-off type can be removed, beside being withdrawn", async () => {
  listContentEntries
    .mockResolvedValueOnce({
      items: [
        { ...entry, id: "out", title: "Wpis na stronie", state: "published" },
        { ...entry, id: "draft", title: "Szkic wpisu", state: "draft" },
      ],
      next_cursor: null,
    })
    .mockResolvedValue({ items: [], next_cursor: null });
  previewEntryRemoval.mockResolvedValue({
    entry_id: "draft",
    title: "Szkic wpisu",
    locale: "pl",
    removed: false,
    published: false,
    path: null,
    scheduled: false,
    machine_translation: false,
    other_languages: [],
  });
  removeContentEntry.mockResolvedValue({});
  renderPanel(off.id);

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Działania dla wpisu Szkic wpisu",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń wpis…" }));
  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByText(
      "Wpis nie jest na stronie. Zniknie z listy wpisów.",
    ),
  ).not.toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń wpis" }));

  await waitFor(() => expect(removeContentEntry).toHaveBeenCalledWith("draft"));
  // The list is read again, without the removed entry.
  await waitFor(() => expect(listContentEntries).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByText("Szkic wpisu")).toBeNull());
});
