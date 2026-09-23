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

import type { DraftSaveInput } from "@saas-core/api-client";
import {
  availablePageTemplates,
  corePageTemplates,
  isRetiredPageTemplate,
  type PageTemplate,
} from "@saas-core/site-blocks";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { registry } from "./block-form";
import { PageEditor, TemplateOption } from "./page-editor";

const {
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
  listMediaAssets,
  listPageTranslations,
  materializeTemplatePhoto,
  savePageDraft,
} = vi.hoisted(() => ({
  getPageDraft: vi.fn(),
  getPageDraftPreview: vi.fn(),
  importPageTemplate: vi.fn(),
  listMediaAssets: vi.fn(),
  listPageTranslations: vi.fn(),
  materializeTemplatePhoto: vi.fn(),
  savePageDraft: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getMediaAssetPreview: vi
    .fn()
    .mockRejectedValue(new Error("Unavailable fixture preview")),
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
  listMediaAssets,
  listPageTranslations,
  materializeTemplatePhoto,
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
const figureAsset = "019ff20d-a000-7000-8000-000000000077";
const legacyText = "Pierwszy akapit.\n\nDrugi akapit.";

function draftWith(
  blocks: Record<string, unknown>[],
  pagePresentation: Record<string, unknown> | null = null,
) {
  return {
    page_id: page.id,
    version: 1,
    draft_id: page.current_draft_id,
    content_hash: page.current_draft_hash,
    created_at: "2026-08-11T12:00:00Z",
    page_presentation: pagePresentation,
    blocks: blocks.map((block, position) => ({
      id: `019ff20d-a000-7000-8000-0000000001${String(position).padStart(2, "0")}`,
      position,
      ...block,
    })),
    media_asset_ids: [],
  };
}

const legacyRichText = {
  block_type: "core.rich_text",
  schema_version: 1,
  data: { text: legacyText },
};

type Draft = ReturnType<typeof draftWith>;
let current: Draft;

/** Serves `draft` and saves the way the API does: an absent
 *  `page_presentation` keeps the stored look, `null` clears it. */
function mockDraft(draft: Draft) {
  current = draft;
  getPageDraft.mockResolvedValue(draft);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockDraft(draftWith([legacyRichText]));
  listPageTranslations.mockResolvedValue({
    page_id: page.id,
    default_locale: "pl",
    supported_locales: ["pl", "en"],
    items: [],
  });
  listMediaAssets.mockResolvedValue({ items: [], next_cursor: null });
  materializeTemplatePhoto.mockResolvedValue({
    asset_id: "019ff20d-a000-7000-8000-000000000099",
  });
  savePageDraft.mockImplementation(
    async (_id: string, input: DraftSaveInput) => {
      const look =
        "page_presentation" in input
          ? ((input.page_presentation ?? null) as Draft["page_presentation"])
          : current.page_presentation;
      current = {
        ...draftWith(
          input.blocks as unknown as Record<string, unknown>[],
          look,
        ),
        version: input.expected_version + 1,
      };
      return current;
    },
  );
});

afterEach(() => cleanup());

function renderEditor(visual = false) {
  render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <PageEditor
        onChanged={vi.fn().mockResolvedValue(undefined)}
        page={page}
      />
    </NextIntlClientProvider>,
  );
  if (!visual)
    fireEvent.click(screen.getByRole("button", { name: "Formularze" }));
}

function save() {
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
}

function savedInput(call = 0): DraftSaveInput {
  return savePageDraft.mock.calls[call]?.[1] as DraftSaveInput;
}

test("a legacy text opens unchanged in the editor and splits into paragraphs on request", async () => {
  renderEditor();
  const text = await screen.findByRole(
    "textbox",
    { name: "Treść sekcji" },
    // The editor loads on demand (next/dynamic); the first import is slow.
    { timeout: 10_000 },
  );
  await waitFor(() => expect(text.textContent).toBe(legacyText));

  // Saved untouched, the v1 text becomes one paragraph of the latest version
  // (v3 only adds optional fields), every character kept.
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().blocks).toEqual([
    {
      block_type: "core.rich_text",
      schema_version: 3,
      data: {
        content: [{ type: "paragraph", content: [{ text: legacyText }] }],
      },
    },
  ]);
  expect(savedInput()).not.toHaveProperty("page_presentation");

  // The old blank lines become real paragraphs with one click.
  fireEvent.click(screen.getByRole("button", { name: "Podziel na akapity" }));
  // Saving reloads the draft, so the text is looked up again.
  await waitFor(() =>
    expect(
      screen
        .getByRole("textbox", { name: "Treść sekcji" })
        .querySelectorAll("p"),
    ).toHaveLength(2),
  );
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(2));
  expect(savedInput(1).blocks[0].data).toEqual({
    content: [
      { type: "paragraph", content: [{ text: "Pierwszy akapit." }] },
      { type: "paragraph", content: [{ text: "Drugi akapit." }] },
    ],
  });
  expect(
    screen.queryByRole("button", { name: "Podziel na akapity" }),
  ).toBeNull();
}, 45_000);

test("an illustration inside the text is referenced when the page is saved", async () => {
  mockDraft(
    draftWith([
      {
        block_type: "core.rich_text",
        schema_version: 2,
        data: {
          layout: "column",
          content: [
            { type: "paragraph", content: [{ text: "Tekst." }] },
            {
              type: "figure",
              image: { asset_id: figureAsset, alt: "Pastwisko" },
              caption: "Podpis",
            },
          ],
        },
      },
    ]),
  );
  renderEditor();
  const text = await screen.findByRole(
    "textbox",
    { name: "Treść sekcji" },
    // The editor loads on demand (next/dynamic); the first import is slow.
    { timeout: 10_000 },
  );
  // The figure is a card in the text, with its fields.
  expect(await within(text).findByDisplayValue("Pastwisko")).not.toBeNull();
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().media_asset_ids).toEqual([figureAsset]);
  expect(savedInput().blocks[0].data).toMatchObject({
    content: [
      { type: "paragraph" },
      { type: "figure", image: { asset_id: figureAsset, alt: "Pastwisko" } },
    ],
  });
});

test("section width and surface are saved beside the content and reset removes them", async () => {
  mockDraft(
    draftWith([
      {
        block_type: "core.hero",
        schema_version: 5,
        data: { title: "Tytuł", layout: "classic" },
      },
    ]),
  );
  renderEditor(true);
  await screen.findByLabelText("Nagłówek");
  fireEvent.change(screen.getByLabelText("Szerokość treści"), {
    target: { value: "narrow" },
  });
  fireEvent.change(screen.getByLabelText("Tło sekcji"), {
    target: { value: "inverse" },
  });
  expect(
    screen.getByTestId("live-canvas").querySelector(".site-presentation"),
  ).toHaveClass(
    "site-presentation--inner-narrow",
    "site-presentation--surface-inverse",
  );
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().blocks[0]).toEqual({
    block_type: "core.hero",
    schema_version: registry.definitions.get("core.hero")?.latestVersion,
    data: { title: "Tytuł", layout: "classic" },
    presentation: { schemaVersion: 2, inner: "narrow", surface: "inverse" },
  });

  fireEvent.click(
    screen.getByRole("button", {
      name: polishMessages.Sites.sectionPresentation.reset,
    }),
  );
  expect(
    screen.getByTestId("live-canvas").querySelector(".site-presentation"),
  ).toBeNull();
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(2));
  expect(savedInput(1).blocks[0]).not.toHaveProperty("presentation");
});

test("this page's look reaches the canvas, is saved only when changed, and reset sends null", async () => {
  mockDraft(draftWith([legacyRichText], { schemaVersion: 1, width: "full" }));
  renderEditor(true);
  const canvas = await screen.findByTestId("live-canvas");
  await waitFor(() => expect(canvas).toHaveClass("site-page--full"));

  fireEvent.click(
    screen.getByRole("button", { name: polishMessages.Sites.studio.design }),
  );
  fireEvent.change(screen.getByLabelText("Font nagłówków"), {
    target: { value: "lora" },
  });
  expect(canvas).toHaveClass("site-page--full", "site-heading-font--lora");
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().page_presentation).toEqual({
    schemaVersion: 1,
    width: "full",
    headingFont: "lora",
  });

  // Saved and reloaded as the new baseline: a second save sends nothing.
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(2));
  expect(savedInput(1)).not.toHaveProperty("page_presentation");

  fireEvent.click(
    screen.getByRole("button", {
      name: polishMessages.Sites.pagePresentation.reset,
    }),
  );
  expect(canvas).not.toHaveClass("site-page--full");
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(canvas).toHaveClass("site-page--full", "site-heading-font--lora");
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(3));
  expect(savedInput(2).page_presentation).toBeNull();
}, 45_000);

test("inserting the same chapters layout twice keeps heading anchors unique on the page", async () => {
  mockDraft(draftWith([]));
  renderEditor(true);
  const rail = await screen.findByRole("complementary", {
    name: polishMessages.Sites.studio.pageNavigation,
  });
  fireEvent.click(
    within(rail).getByRole("button", {
      name: polishMessages.Sites.sectionLibrary.open,
    }),
  );
  fireEvent.change(within(rail).getByLabelText("Kategoria"), {
    target: { value: "core.rich_text" },
  });
  const add = within(rail).getByRole("button", {
    name: "Dodaj: Rozdziały z indeksem",
  });
  fireEvent.click(add);
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: /Edytuj sekcję/ }),
    ).toHaveLength(1),
  );
  fireEvent.click(add);
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: /Edytuj sekcję/ }),
    ).toHaveLength(2),
  );
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  const anchors = savedInput().blocks.flatMap((block) =>
    (block.data as { content: { type: string; anchor?: string }[] }).content
      .filter((node) => node.type === "heading")
      .map((node) => node.anchor),
  );
  expect(anchors.length).toBeGreaterThan(2);
  expect(new Set(anchors).size).toBe(anchors.length);
}, 45_000);

test("editing a word on the canvas writes the exact run of the rich text", async () => {
  mockDraft(
    draftWith([
      {
        block_type: "core.rich_text",
        schema_version: 2,
        data: {
          layout: "column",
          title: "Tytuł sekcji",
          content: [
            {
              type: "paragraph",
              content: [{ text: "Zwykły " }, { text: "ważny", bold: true }],
            },
            {
              type: "heading",
              level: 2,
              anchor: "plan",
              text: "Plan",
            },
          ],
        },
      },
    ]),
  );
  renderEditor(true);
  const canvas = await screen.findByTestId("live-canvas");
  const edit = within(canvas).getAllByRole("button", {
    name: "Edytuj na podglądzie: Treść sekcji",
  });
  // Runs of the paragraph plus the heading: each is its own control.
  expect(edit).toHaveLength(3);
  fireEvent.click(edit[1]);
  const input = within(canvas).getByRole("textbox", {
    name: "Edytuj na podglądzie: Treść sekcji",
  });
  fireEvent.change(input, { target: { value: "najważniejszy" } });
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  // The commit re-renders the canvas; save what the page now shows.
  await waitFor(() => expect(canvas).toHaveTextContent("najważniejszy"));
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().blocks[0].data).toMatchObject({
    content: [
      {
        type: "paragraph",
        content: [{ text: "Zwykły " }, { text: "najważniejszy", bold: true }],
      },
      { type: "heading", anchor: "plan", text: "Plan" },
    ],
  });
});

test("the template gallery shows the new recipes with their bundled photos", async () => {
  mockDraft(draftWith([]));
  renderEditor(true);
  const rail = await screen.findByRole("complementary", {
    name: polishMessages.Sites.studio.pageNavigation,
  });
  fireEvent.click(
    within(rail).getByRole("button", {
      name: polishMessages.Sites.studio.pageTemplates,
    }),
  );
  for (const name of [
    "Produkt — pierwsze wrażenie",
    "Usługa — przewodnik",
    "Ekspert i wiedza",
  ])
    expect(
      within(rail).getByRole("button", {
        name: new RegExp(`^Użyj szablonu .*${name}`),
      }),
    ).toBeDefined();
  const images = [...rail.querySelectorAll("img")];
  expect(images.length).toBeGreaterThan(0);
  for (const image of images)
    expect(image.getAttribute("src") ?? "").not.toContain("/media/");
  expect(importPageTemplate).not.toHaveBeenCalled();
});

test("a page style reaches the canvas root, is saved as v2 and reset sends null", async () => {
  renderEditor(true);
  const canvas = await screen.findByTestId("live-canvas");
  fireEvent.click(
    screen.getByRole("button", { name: polishMessages.Sites.studio.design }),
  );
  const t = polishMessages.Sites.pagePresentation;
  fireEvent.change(screen.getByLabelText(t.fields.style), {
    target: { value: "editorial" },
  });
  expect(canvas).toHaveClass("site-style--editorial");
  expect(
    screen.getByText(t.styles.editorial.description, { exact: false }),
  ).toBeDefined();
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().page_presentation).toEqual({
    schemaVersion: 2,
    style: "editorial",
  });

  fireEvent.click(screen.getByRole("button", { name: t.reset }));
  expect(canvas).not.toHaveClass("site-style--editorial");
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(2));
  expect(savedInput(1).page_presentation).toBeNull();
});

test("a section anchor is checked against the page, saved as v2 and renamed on duplicate", async () => {
  mockDraft(
    draftWith([
      {
        block_type: "core.hero",
        schema_version: 5,
        data: { title: "Tytuł", layout: "classic" },
      },
      {
        block_type: "core.rich_text",
        schema_version: 3,
        data: {
          content: [
            { type: "heading", level: 2, anchor: "kontakt", text: "Kontakt" },
          ],
        },
      },
    ]),
  );
  renderEditor(true);
  await screen.findByLabelText("Nagłówek");
  const t = polishMessages.Sites;
  const anchor = screen.getByLabelText(t.sectionPresentation.fields.anchor);
  fireEvent.change(anchor, { target: { value: "kontakt" } });
  expect(screen.getByText(t.richText.anchorTaken)).toBeDefined();
  fireEvent.change(anchor, { target: { value: "formularz" } });
  expect(screen.queryByText(t.richText.anchorTaken)).toBeNull();
  expect(screen.getByText("#formularz")).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: t.studio.duplicate }));
  save();
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savedInput().blocks.map((block) => block.presentation)).toEqual([
    { schemaVersion: 2, anchor: "formularz" },
    { schemaVersion: 2, anchor: "formularz-2" },
    undefined,
  ]);
}, 45_000);

test("the gallery offers no retired template and labels each recipe's goal", async () => {
  mockDraft(draftWith([]));
  renderEditor(true);
  const rail = await screen.findByRole("complementary", {
    name: polishMessages.Sites.studio.pageNavigation,
  });
  fireEvent.click(
    within(rail).getByRole("button", {
      name: polishMessages.Sites.studio.pageTemplates,
    }),
  );
  const offered = availablePageTemplates(registry, ["sites.enabled"]);
  const retired = corePageTemplates().filter((template) =>
    isRetiredPageTemplate(template.id),
  );
  expect(retired.length).toBeGreaterThan(0);
  expect(
    within(rail).getAllByRole("button", { name: /^Użyj szablonu / }),
  ).toHaveLength(offered.length);
  for (const template of retired)
    expect(
      within(rail).queryByRole("button", {
        name: `Użyj szablonu ${template.labels.pl.name}`,
      }),
    ).toBeNull();
  expect(within(rail).queryAllByText(/^Cel: /)).toHaveLength(
    offered.filter((template) => template.conversion).length,
  );
});

test.each([
  ["pl", polishMessages, "Cel: zapytanie ofertowe", "Styl: Redakcyjny"],
  ["en", englishMessages, "Goal: inquiry", "Style: Editorial"],
] as const)(
  "a recipe card shows its goal and page style, and the thumbnail wears the style (%s)",
  async (locale, messages, goal, style) => {
    const [base] = availablePageTemplates(registry, ["sites.enabled"]);
    const template: PageTemplate = {
      ...base,
      pagePresentation: { schemaVersion: 2, style: "editorial" },
      conversion: {
        goal: "inquiry",
        stages: base.blocks.map(() => "interest" as const),
      },
    };
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages}>
        <TemplateOption
          closeLabel="Close"
          loading={false}
          locale={locale}
          onApply={vi.fn()}
          previewLabel="Preview"
          previewTitle="Preview title"
          template={template}
          thumbnailLabel="Thumbnail"
          useLabel="Use"
        />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText(goal)).toBeDefined();
    expect(screen.getByText(style)).toBeDefined();
    expect(
      screen
        .getByRole("img", { name: "Thumbnail" })
        .querySelector(".site-style--editorial"),
    ).not.toBeNull();
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  },
);
