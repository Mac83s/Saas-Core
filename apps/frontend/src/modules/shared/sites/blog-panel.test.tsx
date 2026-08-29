import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { BlogPanel } from "./blog-panel";

const {
  createContentCollection,
  createContentEntry,
  getContentEntryDraft,
  listContentCollections,
  listContentEntries,
  publishContentEntry,
  saveContentEntryDraft,
  scheduleContentEntry,
  cancelContentEntrySchedule,
  setContentEntryTags,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  withdrawContentEntry,
  listEntryTranslations,
  createEntryTranslation,
} = vi.hoisted(() => ({
  createContentCollection: vi.fn(),
  createContentEntry: vi.fn(),
  getContentEntryDraft: vi.fn(),
  listContentCollections: vi.fn(),
  listContentEntries: vi.fn(),
  publishContentEntry: vi.fn(),
  saveContentEntryDraft: vi.fn(),
  scheduleContentEntry: vi.fn(),
  cancelContentEntrySchedule: vi.fn(),
  setContentEntryTags: vi.fn(),
  setCollectionAutomationPolicy: vi.fn(),
  setCollectionNavigation: vi.fn(),
  withdrawContentEntry: vi.fn(),
  listEntryTranslations: vi.fn(),
  createEntryTranslation: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createContentCollection,
  createContentEntry,
  getContentEntryDraft,
  listContentCollections,
  listContentEntries,
  publishContentEntry,
  saveContentEntryDraft,
  scheduleContentEntry,
  cancelContentEntrySchedule,
  setContentEntryTags,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  withdrawContentEntry,
  listEntryTranslations,
  createEntryTranslation,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const collectionId = "019ff20d-a000-7000-8000-000000000020";
const entryId = "019ff20d-a000-7000-8000-000000000030";

const collection = {
  id: collectionId,
  site_id: siteId,
  key: "blog",
  name: "Blog",
  kind: "blog",
  base_path: "blog",
  automation_policy: "manual",
  show_in_navigation: false,
};

const entry = {
  id: entryId,
  collection_id: collectionId,
  slug: "pierwszy-wpis",
  locale: "pl",
  title: "Pierwszy wpis",
  excerpt: "",
  author_name: "",
  state: "draft",
  version: 2,
  published_at: null,
  publication_id: null,
  noindex: false,
  draft_author: null,
  translation_group: "019ff20d-a000-7000-8000-000000000040",
  schedule_state: "none",
  scheduled_publish_at: null,
  schedule_error: "",
  tags: [],
};

function renderPanel() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <BlogPanel siteId={siteId} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listContentCollections.mockResolvedValue([collection]);
  listContentEntries.mockResolvedValue({ items: [entry], next_cursor: null });
  listEntryTranslations.mockResolvedValue([entry]);
  createEntryTranslation.mockResolvedValue({
    ...entry,
    id: "translated",
    locale: "en",
    slug: "in-english",
    title: "In English",
  });
  getContentEntryDraft.mockResolvedValue({
    entry_id: entryId,
    version: 2,
    blocks: [],
  });
  createContentEntry.mockResolvedValue({ ...entry, id: "new-entry" });
  publishContentEntry.mockResolvedValue({
    id: "publication",
    entry_id: entryId,
    sequence: 1,
    snapshot_hash: "a".repeat(64),
  });
  withdrawContentEntry.mockResolvedValue({ ...entry, state: "draft" });
  setCollectionNavigation.mockResolvedValue({
    ...collection,
    show_in_navigation: true,
  });
  setCollectionAutomationPolicy.mockResolvedValue({
    ...collection,
    automation_policy: "automated",
  });
  saveContentEntryDraft.mockResolvedValue({
    entry_id: entryId,
    version: 3,
    blocks: [],
  });
});

test("derives the entry address from its title", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Tytuł"), {
    target: { value: "Zażółć gęślą jaźń" },
  });

  // Typing the address a second time is where it drifts from the title, so the
  // panel suggests it — transliterated the same way the API normalises it.
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Adres wpisu") as HTMLInputElement).value,
    ).toBe("zazolc-gesla-jazn"),
  );

  fireEvent.click(screen.getByRole("button", { name: "Dodaj wpis" }));
  await waitFor(() => expect(createContentEntry).toHaveBeenCalledOnce());
  expect(createContentEntry.mock.calls[0]?.[1]).toEqual({
    title: "Zażółć gęślą jaźń",
    slug: "zazolc-gesla-jazn",
    locale: "pl",
  });
});

test("publishes a draft entry and reloads the list", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Opublikuj wpis Pierwszy wpis" }),
  );

  await waitFor(() => expect(publishContentEntry).toHaveBeenCalledOnce());
  expect(publishContentEntry.mock.calls[0]?.[0]).toBe(entryId);
  // The list is refetched rather than patched locally: publication also moves
  // `published_at`, which only the server knows.
  await waitFor(() => expect(listContentEntries).toHaveBeenCalledTimes(2));
});

test("hands the blog to automation and warns before an entry is edited", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Kto redaguje tę treść"), {
    target: { value: "automated" },
  });

  await waitFor(() =>
    expect(setCollectionAutomationPolicy).toHaveBeenCalledWith(
      collectionId,
      "automated",
    ),
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Edytuj wpis Pierwszy wpis" }),
  );

  // The API is what refuses the save (403 page_automation_forbidden); saying so
  // first spares the operator a form that was never going to be accepted.
  expect(
    await screen.findByText(/Ten wpis prowadzi automatyzacja/),
  ).not.toBeNull();
});

test("reports a server refusal instead of pretending the entry was created", async () => {
  createContentEntry.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Forbidden",
      status: 403,
      code: "page_automation_forbidden",
      detail: "Treść prowadzi automatyzacja.",
      correlation_id: null,
    }),
  );
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Tytuł"), {
    target: { value: "Drugi wpis" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Dodaj wpis" }));

  expect(await screen.findByRole("alert")).not.toBeNull();
  expect(screen.getByRole("alert").textContent).toContain(
    "Treść prowadzi automatyzacja.",
  );
});

test("offers to create a blog when the site has none, and stays accessible", async () => {
  listContentCollections.mockResolvedValueOnce([]);
  createContentCollection.mockResolvedValue(collection);
  const rendered = renderPanel();

  expect(await screen.findByLabelText("Nazwa")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Nazwa"), {
    target: { value: "Blog firmowy" },
  });
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Adres bloga") as HTMLInputElement).value,
    ).toBe("blog-firmowy"),
  );

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  fireEvent.click(screen.getByRole("button", { name: "Załóż blog" }));
  await waitFor(() => expect(createContentCollection).toHaveBeenCalledOnce());
  expect(createContentCollection.mock.calls[0]?.[1]).toEqual({
    key: "blog-firmowy",
    name: "Blog firmowy",
    kind: "blog",
    base_path: "blog-firmowy",
  });
});

test("saves the entry draft and confirms it", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Edytuj wpis Pierwszy wpis" }),
  );

  expect(
    await screen.findByRole("button", { name: "Zapisz nową wersję draftu" }),
  ).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  await waitFor(() => expect(saveContentEntryDraft).toHaveBeenCalledOnce());
  // The version the server returned is what the next save must send, so the
  // confirmation is also the proof the editor took it.
  expect(saveContentEntryDraft.mock.calls[0]?.[1]).toEqual({
    expected_version: 2,
    blocks: [],
    // Collected from the blocks themselves, so an article with no picture
    // sends an empty list rather than omitting the field.
    media_asset_ids: [],
  });
  expect((await screen.findByRole("status")).textContent).toContain(
    "Szkic został zapisany.",
  );
});

test("offers the middle setting and marks what the automation proposed", async () => {
  setCollectionAutomationPolicy.mockResolvedValueOnce({
    ...collection,
    automation_policy: "proposed",
  });
  listContentEntries.mockResolvedValue({
    items: [{ ...entry, draft_author: "automation" }],
    next_cursor: null,
  });
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  // A proposal has to be recognisable in the list, or accepting one is a guess.
  expect(screen.getByText("Propozycja")).not.toBeNull();

  fireEvent.change(screen.getByLabelText("Kto redaguje tę treść"), {
    target: { value: "proposed" },
  });
  await waitFor(() =>
    expect(setCollectionAutomationPolicy).toHaveBeenCalledWith(
      collectionId,
      "proposed",
    ),
  );
  expect(
    screen.getByText(/to Ty decydujesz, czy zostanie opublikowana/),
  ).not.toBeNull();

  fireEvent.click(
    screen.getByRole("button", { name: "Edytuj wpis Pierwszy wpis" }),
  );
  // Publishing is the act of accepting, so the editor says so rather than
  // leaving the operator to guess whose words are on screen.
  expect(
    await screen.findByText(/Publikacja oznacza akceptację propozycji/),
  ).not.toBeNull();
});

test("links the blog into the site menu and says when it takes effect", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.click(screen.getByLabelText(/Pokaż blog w menu witryny/));

  await waitFor(() =>
    expect(setCollectionNavigation).toHaveBeenCalledWith(collectionId, true),
  );
  // The menu a visitor sees comes from the last publication, so promising an
  // immediate change would be a lie.
  expect(screen.getByText(/po najbliższej publikacji witryny/)).not.toBeNull();
});

test("adds a language version and keeps it a separate publication", async () => {
  renderPanel();

  expect(await screen.findByText("Pierwszy wpis")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Edytuj wpis Pierwszy wpis" }),
  );

  expect(await screen.findByText("Wersje językowe")).not.toBeNull();
  // Labelled distinctly from the "new entry" form: two fields with the same
  // accessible name on one screen is a real problem, not a test problem.
  fireEvent.change(screen.getByLabelText("Tytuł wersji językowej"), {
    target: { value: "In English" },
  });
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Adres wersji językowej") as HTMLInputElement)
        .value,
    ).toBe("in-english"),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj wersję językową" }),
  );

  await waitFor(() => expect(createEntryTranslation).toHaveBeenCalledOnce());
  expect(createEntryTranslation.mock.calls[0]?.[1]).toEqual({
    locale: "en",
    slug: "in-english",
    title: "In English",
  });
});

test("planuje publikację wpisu na wskazaną godzinę", async () => {
  scheduleContentEntry.mockResolvedValue({
    entry_id: entryId,
    schedule_state: "pending",
    scheduled_publish_at: "2026-09-01T05:00:00Z",
    schedule_error: "",
  });
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: /Edytuj/ }));

  const field = await screen.findByLabelText("Opublikuj o godzinie");
  fireEvent.change(field, { target: { value: "2026-09-01T07:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Zaplanuj publikację" }));

  await waitFor(() => expect(scheduleContentEntry).toHaveBeenCalledOnce());
  expect(scheduleContentEntry.mock.calls[0]?.[0]).toBe(entryId);
  // Sent as an absolute instant: "Monday 07:00" has to mean the operator's
  // Monday, not the server's.
  expect(scheduleContentEntry.mock.calls[0]?.[1]).toBe(
    new Date("2026-09-01T07:00").toISOString(),
  );
});

test("pokazuje, że zaplanowana publikacja się nie udała", async () => {
  listContentEntries.mockResolvedValue({
    items: [
      {
        ...entry,
        schedule_state: "failed",
        scheduled_publish_at: "2026-08-24T05:00:00Z",
        schedule_error: "Plan nie obejmuje publikacji.",
      },
    ],
    next_cursor: null,
  });
  const rendered = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: /Edytuj/ }));

  // A failed publication has to look different from one nobody scheduled, or
  // the operator learns about it from a reader.
  expect(await screen.findByText("Publikacja się nie udała")).not.toBeNull();
  expect(
    screen.getByText("Powód: Plan nie obejmuje publikacji."),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("zapisuje tematy wpisane po przecinku", async () => {
  setContentEntryTags.mockResolvedValue([
    { slug: "porady", name: "Porady" },
    { slug: "dieta", name: "Dieta" },
  ]);
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: /Edytuj/ }));

  fireEvent.change(await screen.findByLabelText("Tematy, po przecinku"), {
    target: { value: " Porady , Dieta ,, " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz tematy" }));

  await waitFor(() => expect(setContentEntryTags).toHaveBeenCalledOnce());
  // Trimmed, and empty pieces dropped: a trailing comma is a typo, not a tag.
  expect(setContentEntryTags.mock.calls[0]?.[1]).toEqual(["Porady", "Dieta"]);
});

test("publikuje ponownie wpis, ktorego tresc zmienila sie po publikacji", async () => {
  listContentEntries.mockResolvedValue({
    items: [
      {
        ...entry,
        state: "published",
        publication_id: "019ff20d-a000-7000-8000-000000000050",
      },
    ],
    next_cursor: null,
  });
  publishContentEntry.mockResolvedValue({
    id: "019ff20d-a000-7000-8000-0000000000f1",
  });
  renderPanel();

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Opublikuj ponownie wpis Pierwszy wpis",
    }),
  );

  // Without this the only way to publish a change to a live article was to
  // withdraw it first, which takes it off the site in the meantime.
  await waitFor(() => expect(publishContentEntry).toHaveBeenCalledOnce());
  expect(publishContentEntry.mock.calls[0]?.[0]).toBe(entryId);
});
