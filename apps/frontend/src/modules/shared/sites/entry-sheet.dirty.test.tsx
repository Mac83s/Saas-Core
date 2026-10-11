import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { ContentEntry } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import type { Editor } from "@tiptap/core";

import { IDLE_COMMIT_MS } from "./rich-text-editor";
import { EntrySheet } from "./entry-sheet";

const {
  getBookingSetup,
  getContentEntryDraft,
  listMediaAssets,
  saveContentEntryDraft,
  updateContentEntryMetadata,
} = vi.hoisted(() => ({
  getBookingSetup: vi.fn(),
  getContentEntryDraft: vi.fn(),
  listMediaAssets: vi.fn(),
  saveContentEntryDraft: vi.fn(),
  updateContentEntryMetadata: vi.fn(),
}));

vi.mock("../../../product", () => ({ product: {} }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getBookingSetup,
  getContentEntryDraft,
  listMediaAssets,
  saveContentEntryDraft,
  updateContentEntryMetadata,
}));
// The panels that make their own requests are not what this is about.
vi.mock("./entry-address", () => ({ EntryAddress: () => null }));
vi.mock("./entry-categories", () => ({ EntryCategories: () => null }));
vi.mock("./entry-tags", () => ({ EntryTags: () => null }));
vi.mock("./entry-schedule", () => ({ EntrySchedule: () => null }));
vi.mock("./entry-translations", () => ({ EntryTranslations: () => null }));

const asset = "019ff20d-a000-7000-8000-000000000077";

/** PostgreSQL's jsonb hands object keys back shortest first, then
 *  alphabetically — not in the order the editor writes them. Imported content
 *  comes from there, so the fixtures are put in that order. */
function jsonbOrder<T>(value: T): T {
  if (Array.isArray(value)) return value.map(jsonbOrder) as T;
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.length - b.length || (a < b ? -1 : 1))
        .map(([key, item]) => [key, jsonbOrder(item)]),
    ) as T;
  return value;
}
const entry = {
  id: "019ff20d-a000-7000-8000-0000000000e1",
  version: 3,
  title: "Jak zadbać o szczeniaka — Как ухаживать",
  excerpt: "Krótki opis wpisu.",
  author_name: "Zespół Puppily",
  noindex: false,
  state: "published",
  categories: [],
  tags: [],
  schedule_state: "none",
  draft_author: null,
  translation_of: null,
} as unknown as ContentEntry;

/** What the HTML importer writes (`html_blocks.py`): rich text cut around a
 *  table, an FAQ, a separator; headings with anchors, lists, a quote with its
 *  source, a figure with a caption, links, Polish and Cyrillic words. */
const imported = jsonbOrder([
  {
    block_type: "core.rich_text",
    schema_version: 4,
    data: {
      content: [
        {
          type: "heading",
          level: 2,
          anchor: "wstep-zolc",
          text: "Wstęp — żółć i gęś",
        },
        {
          type: "paragraph",
          content: [
            { text: "Pierwsze zdania, " },
            { text: "pogrubione", bold: true },
            { text: " oraz " },
            { text: "pochylone", italic: true },
            { text: " i " },
            { text: "odnośnik", href: "https://example.com/psy" },
            { text: ". Привет, мир — щенок." },
          ],
        },
        {
          type: "list",
          style: "bullet",
          items: [
            { content: [{ text: "Pierwszy punkt" }] },
            {
              content: [{ text: "Drugi punkt" }],
              children: {
                style: "ordered",
                items: [{ content: [{ text: "Zagnieżdżony" }] }],
              },
            },
          ],
        },
        {
          type: "quote",
          content: [{ text: "Pies to przyjaciel." }],
          source: "Książka",
        },
        {
          type: "figure",
          image: { asset_id: asset, alt: "Szczeniak na trawie" },
          caption: "Podpis zdjęcia",
        },
        { type: "heading", level: 3, anchor: "ostatni", text: "Ostatni" },
        { type: "paragraph", content: [{ text: "Koniec." }] },
      ],
    },
  },
  {
    block_type: "core.table",
    schema_version: 1,
    data: {
      caption: "Tabela wag",
      header: "row",
      rows: [
        {
          cells: [
            { content: [{ text: "Rasa" }] },
            { content: [{ text: "Waga" }] },
            {},
          ],
        },
        {
          cells: [
            { content: [{ text: "Labrador" }] },
            { content: [{ text: "30 kg", bold: true }] },
            {},
          ],
        },
      ],
    },
  },
  {
    block_type: "core.faq",
    schema_version: 3,
    data: {
      title: "Pytania",
      items: [
        { question: "Ile śpi szczeniak?", answer: "Dużo.\n\nNaprawdę dużo." },
      ],
    },
  },
  {
    block_type: "core.separator",
    schema_version: 1,
    data: { layout: "line" },
  },
]);

function renderSheet() {
  const onClose = vi.fn();
  const view = render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <EntrySheet
        busy={false}
        collection={null}
        entry={entry}
        languageName="polski"
        onChanged={async () => undefined}
        onClose={onClose}
        onPublish={() => undefined}
        onRemove={() => undefined}
        onWithdraw={() => undefined}
        returnFocus={() => null}
        siteId="019ff20d-a000-7000-8000-000000000010"
        stateLabel="Opublikowany"
      />
    </NextIntlClientProvider>,
  );
  return { ...view, onClose };
}

/** The blocks are on screen and the editor's idle write (if it makes one at
 *  load) has had its time. */
async function loaded() {
  await screen.findByRole("button", { name: "Zapisz szkic" });
  await waitFor(() =>
    expect(document.querySelector(".ProseMirror")).not.toBeNull(),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, IDLE_COMMIT_MS + 400));
  });
}

const badge = () => screen.queryByText("Niezapisane zmiany", { exact: true });
const field = (name: string) =>
  document.getElementById(`entry-${name}-${entry.id}`) as HTMLInputElement;
const proseMirror = () =>
  document.querySelector(".ProseMirror") as HTMLElement & { editor: Editor };

/** One character into the first paragraph that has words, as typing would. */
function typeIntoParagraph(character: string) {
  const { editor } = proseMirror();
  let at = -1;
  editor.state.doc.descendants((node, position) => {
    if (at < 0 && node.type.name === "paragraph" && node.textContent)
      at = position + 1;
  });
  act(() => {
    editor.commands.insertContentAt(at, character);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  getBookingSetup.mockResolvedValue({ services: [], resources: [] });
  listMediaAssets.mockResolvedValue({
    items: [{ id: asset, original_filename: "szczeniak.jpg", ai_origin: null }],
  });
  getContentEntryDraft.mockResolvedValue({ version: 3, blocks: imported });
  saveContentEntryDraft.mockResolvedValue({ version: 4 });
  updateContentEntryMetadata.mockResolvedValue({});
});

afterEach(() => cleanup());

test("an imported entry opens clean, and closing it does not ask", async () => {
  const { onClose } = renderSheet();
  await loaded();
  expect(badge()).toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, {
    key: "Escape",
  });
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(screen.queryByText("Masz niezapisane zmiany")).toBeNull();
});

test("an entry whose blocks lack their optional fields opens clean", async () => {
  getContentEntryDraft.mockResolvedValue({
    version: 3,
    blocks: jsonbOrder([
      imported[0],
      {
        block_type: "core.table",
        schema_version: 1,
        data: {
          header: "none",
          rows: [{ cells: [{ content: [{ text: "A" }] }, {}] }],
        },
      },
      {
        block_type: "core.faq",
        schema_version: 3,
        data: { items: [{ question: "Pytanie?", answer: "Odpowiedź." }] },
      },
      { block_type: "core.separator", schema_version: 1, data: {} },
    ]),
  });
  renderSheet();
  await loaded();
  expect(badge()).toBeNull();
});

test("looking into the editor and leaving it, with nothing typed, changes nothing", async () => {
  renderSheet();
  await loaded();
  fireEvent.focus(proseMirror());
  fireEvent.blur(proseMirror());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, IDLE_COMMIT_MS + 200));
  });
  expect(badge()).toBeNull();
});

test("one character in the title asks, and saving the words makes the entry clean again", async () => {
  renderSheet();
  await loaded();
  fireEvent.change(field("title"), {
    target: { value: `${entry.title}!` },
  });
  await waitFor(() => expect(badge()).not.toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Zapisz dane wpisu" }));
  await waitFor(() => expect(updateContentEntryMetadata).toHaveBeenCalled());
  await waitFor(() => expect(badge()).toBeNull());
});

test("one character in the author asks, and putting it back makes the entry clean again", async () => {
  renderSheet();
  await loaded();
  fireEvent.change(field("author"), {
    target: { value: `${entry.author_name}x` },
  });
  await waitFor(() => expect(badge()).not.toBeNull());
  fireEvent.change(field("author"), { target: { value: entry.author_name } });
  await waitFor(() => expect(badge()).toBeNull());
});

test("one character in a paragraph asks, and saving the draft makes the entry clean again", async () => {
  renderSheet();
  await loaded();
  typeIntoParagraph("x");
  await waitFor(() => expect(badge()).not.toBeNull(), { timeout: 3000 });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
  await waitFor(() => expect(saveContentEntryDraft).toHaveBeenCalled());
  await waitFor(() => expect(badge()).toBeNull());
});

test("choosing a layout and choosing the first one again leaves the entry as it was", async () => {
  renderSheet();
  await loaded();
  const layout = document.getElementById("block-layout-0") as HTMLSelectElement;
  const other = [...layout.options].find((option) => option.value !== "");
  fireEvent.change(layout, { target: { value: other!.value } });
  await waitFor(() => expect(badge()).not.toBeNull());
  fireEvent.change(layout, { target: { value: "" } });
  await waitFor(() => expect(badge()).toBeNull());
});
