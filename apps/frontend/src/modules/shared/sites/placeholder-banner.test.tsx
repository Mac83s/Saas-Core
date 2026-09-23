import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageEditor } from "./page-editor";

const { getPageDraft, listMediaAssets, listPageTranslations, savePageDraft } =
  vi.hoisted(() => ({
    getPageDraft: vi.fn(),
    listMediaAssets: vi.fn(),
    listPageTranslations: vi.fn(),
    savePageDraft: vi.fn(),
  }));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getMediaAssetPreview: vi
    .fn()
    .mockRejectedValue(new Error("Unavailable fixture preview")),
  getPageDraft,
  listMediaAssets,
  listPageTranslations,
  savePageDraft,
}));

const page = {
  id: "019ff20d-a000-7000-8000-000000000020",
  site_id: "019ff20d-a000-7000-8000-000000000010",
  name: "Start",
  key: "home",
  version: 1,
  current_draft_id: "019ff20d-a000-7000-8000-000000000021",
  current_draft_hash: "a".repeat(64),
  page_type: "landing",
  automation_policy: "manual",
  draft_author: null,
  created_at: "2026-08-11T12:00:00Z",
  updated_at: "2026-08-11T12:00:00Z",
};

function draftWith(blocks: Record<string, unknown>[]) {
  return {
    page_id: page.id,
    version: 1,
    draft_id: page.current_draft_id,
    content_hash: page.current_draft_hash,
    created_at: "2026-08-11T12:00:00Z",
    page_presentation: null,
    blocks: blocks.map((block, position) => ({
      id: `019ff20d-a000-7000-8000-0000000001${String(position).padStart(2, "0")}`,
      position,
      ...block,
    })),
    media_asset_ids: [],
  };
}

/** Two markers in the text of the first section, one in an entry of the second. */
function proofDraft(marker: string) {
  return draftWith([
    {
      block_type: "core.rich_text",
      schema_version: 2,
      data: {
        layout: "column",
        title: "O nas",
        content: [
          {
            type: "paragraph",
            content: [{ text: `[${marker}: opinia klienta]` }],
          },
          {
            type: "paragraph",
            content: [{ text: `Pracujemy od [${marker}: liczba] lat.` }],
          },
        ],
      },
    },
    {
      block_type: "core.feature_list",
      schema_version: 4,
      data: {
        title: "Dlaczego my",
        items: [{ title: "Termin", text: `[${marker}: czas odpowiedzi]` }],
      },
    },
  ]);
}

beforeEach(() => {
  vi.clearAllMocks();
  listPageTranslations.mockResolvedValue({
    page_id: page.id,
    default_locale: "pl",
    supported_locales: ["pl", "en"],
    items: [],
  });
  listMediaAssets.mockResolvedValue({ items: [], next_cursor: null });
  savePageDraft.mockImplementation(async () => getPageDraft());
});

afterEach(() => cleanup());

function renderEditor(
  locale: "pl" | "en",
  messages: typeof polishMessages | typeof englishMessages,
  onChanged = vi.fn().mockResolvedValue(undefined),
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Europe/Warsaw"
    >
      <PageEditor onChanged={onChanged} page={page} />
    </NextIntlClientProvider>,
  );
}

test.each([
  {
    locale: "pl",
    messages: polishMessages,
    marker: "Uzupełnij",
    three: "Na tej stronie zostały 3 miejsca do uzupełnienia.",
    two: "Na tej stronie zostały 2 miejsca do uzupełnienia.",
    firstSection: "1. O nas 2 miejsca do uzupełnienia",
    secondSection: "2. Dlaczego my 1 miejsce do uzupełnienia",
    firstBadge: "2 miejsca do uzupełnienia",
    secondBadge: "1 miejsce do uzupełnienia",
  },
  {
    locale: "en",
    messages: englishMessages,
    marker: "Fill in",
    three: "This page still has 3 places to fill in.",
    two: "This page still has 2 places to fill in.",
    firstSection: "1. O nas 2 places to fill in",
    secondSection: "2. Dlaczego my 1 place to fill in",
    firstBadge: "2 places to fill in",
    secondBadge: "1 place to fill in",
  },
] as const)(
  "$locale: the page says where proof is still missing, leads there and steps aside once it is filled",
  async ({ locale, messages, marker, three, two, ...names }) => {
    getPageDraft.mockResolvedValue(proofDraft(marker));
    const onChanged = vi.fn().mockResolvedValue(undefined);
    const { container } = renderEditor(locale, messages, onChanged);
    const studio = messages.Sites.studio;

    // Above the forms as well as the canvas; polite, never an alert.
    fireEvent.click(await screen.findByRole("button", { name: studio.forms }));
    expect(await screen.findByText(three)).toHaveAttribute("role", "status");
    expect(screen.queryByRole("alert")).toBeNull();
    const sections = screen.getByRole("list", {
      name: studio.placeholders.sections,
    });
    const listed = within(sections).getAllByRole("button");
    expect(listed).toHaveLength(2);
    expect(listed[0]).toHaveAccessibleName(names.firstSection);
    expect(listed[1]).toHaveAccessibleName(names.secondSection);

    // From the forms, a listed section opens in the visual editor.
    fireEvent.click(
      within(sections).getByRole("button", { name: names.secondSection }),
    );
    const inspector = screen.getByRole("complementary", {
      name: studio.inspector,
    });
    await waitFor(() =>
      expect(within(inspector).getByRole("heading")).toHaveTextContent(
        messages.Sites.featureListBlock,
      ),
    );

    // The outline marks both sections with a count that reads as words.
    const outline = within(
      screen.getByRole("complementary", { name: studio.pageNavigation }),
    );
    expect(
      outline.getByRole("button", { name: new RegExp(names.firstBadge) }),
    ).not.toHaveAttribute("aria-current");
    expect(
      outline.getByRole("button", { name: new RegExp(names.secondBadge) }),
    ).toHaveAttribute("aria-current", "true");
    expect(outline.getByTitle(names.firstBadge)).toHaveTextContent("2");

    expect(
      (
        await axe.run(container, {
          rules: { "color-contrast": { enabled: false } },
        })
      ).violations,
    ).toEqual([]);

    // Guidance only: the page saves with the markers still in it.
    const save = screen.getByRole("button", { name: studio.save });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(savePageDraft).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(
        within(inspector).getByLabelText(messages.Sites.text),
      ).toBeEnabled(),
    );

    fireEvent.change(within(inspector).getByLabelText(messages.Sites.text), {
      target: { value: "Odpowiadamy w ciągu doby." },
    });
    expect(await screen.findByText(two)).toHaveAttribute("role", "status");
    expect(
      screen.queryByRole("button", { name: names.secondSection }),
    ).toBeNull();
    expect(
      outline.queryByRole("button", { name: new RegExp(names.secondBadge) }),
    ).toBeNull();

    // On the canvas, a listed section is chosen the way the outline chooses it.
    fireEvent.click(screen.getByRole("button", { name: names.firstSection }));
    await waitFor(() =>
      expect(within(inspector).getByRole("heading")).toHaveTextContent(
        messages.Sites.richTextBlock,
      ),
    );
    // The text's runs are written in place on the canvas.
    const canvas = screen.getByTestId("live-canvas");
    const editRun = messages.Sites.studio.editText.replace(
      "{field}",
      messages.Sites.richTextContent,
    );
    for (const index of [0, 1]) {
      fireEvent.click(
        within(canvas).getAllByRole("button", { name: editRun })[index]!,
      );
      const input = within(canvas).getByRole("textbox", { name: editRun });
      fireEvent.change(input, { target: { value: "Prawdziwa treść." } });
      fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
      await waitFor(() =>
        expect(
          within(canvas).queryByRole("textbox", { name: editRun }),
        ).toBeNull(),
      );
    }
    await waitFor(() => expect(screen.queryByText(two)).toBeNull());
    expect(
      screen.queryByRole("list", { name: studio.placeholders.sections }),
    ).toBeNull();
    expect(outline.queryByTitle(names.firstBadge)).toBeNull();
  },
  // Renders the page editor and the rich text editor it loads on demand:
  // under a full test run on the dev VPS this takes far longer than alone.
  45_000,
);

test("more than three sections to finish fold into a list that opens on demand", async () => {
  getPageDraft.mockResolvedValue(
    draftWith(
      ["Jeden", "Dwa", "Trzy", "Cztery"].map((title) => ({
        block_type: "core.rich_text",
        schema_version: 2,
        data: {
          layout: "column",
          title,
          content: [
            {
              type: "paragraph",
              content: [{ text: "[Uzupełnij: przykład realizacji]" }],
            },
          ],
        },
      })),
    ),
  );
  renderEditor("pl", polishMessages);
  expect(
    await screen.findByText(
      "Na tej stronie zostały 4 miejsca do uzupełnienia.",
    ),
  ).toHaveAttribute("role", "status");
  const list = screen.getByRole("list", {
    name: polishMessages.Sites.studio.placeholders.sections,
  });
  const folded = list.closest("details");
  expect(folded).not.toBeNull();
  expect(folded!.querySelector("summary")).toHaveTextContent("Pokaż 4 sekcje");
  expect(within(list).getAllByRole("button")).toHaveLength(4);
});
