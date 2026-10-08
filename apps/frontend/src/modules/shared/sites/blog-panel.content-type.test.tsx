import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { BlogPanel } from "./blog-panel";

/** The blog screen as one content type's entries (ADR-079 pkt 25,
 *  `/panel/sites/content/<typ>`), and what the blog screen itself does with
 *  a type that is switched off. The blog screen's own behaviour is
 *  `blog-panel.test.tsx`, unchanged by content types. */

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const { getPublicLocales, listContentCollections, listContentEntries } =
  vi.hoisted(() => ({
    getPublicLocales: vi.fn(),
    listContentCollections: vi.fn(),
    listContentEntries: vi.fn(),
  }));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getPublicLocales,
  listContentCollections,
  listContentEntries,
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

test("a switched-off type takes no work and says where to switch it on", async () => {
  renderPanel(off.id);

  expect(
    await screen.findByText(/Ten typ treści jest wyłączony/),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Dodaj wpis" })).toBeNull();
  expect(
    screen.getByRole("link", { name: "Wszystkie typy treści" }),
  ).not.toBeNull();
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
