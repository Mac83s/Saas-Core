import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps } from "react";
import axe from "axe-core";
import { FormProvider, useForm, type FieldValues } from "react-hook-form";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type DraftSaveInput,
  type ImageGenerationOffer,
} from "@saas-core/api-client";
import {
  availablePageTemplates,
  parseSiteAppearance,
  sectionDecorationPresets,
  type SectionDecorationV1,
} from "@saas-core/site-blocks";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { BlockFields, emptyBlock, registry } from "./block-form";
import { PageEditor } from "./page-editor";
import { PageEditorContext } from "./page-editor-context";
import { PublicationHistory } from "./publication-history";
import { RichTextEditor } from "./rich-text-editor";

const offer: ImageGenerationOffer = {
  available: true,
  credit_cost: 2,
  aspects: ["16:9", "4:3", "3:2"],
  badge_visible: true,
};

// The gallery offers whatever recipes are current (retired ones are hidden),
// so the tests follow the first offered one instead of naming it.
const offeredTemplates = availablePageTemplates(registry, ["sites.enabled"]);
const [firstTemplate] = offeredTemplates;
// What leaves the panel is always the hero's latest contract version.
const heroVersion = registry.definitions.get("core.hero")?.latestVersion;

const {
  completeMediaUpload,
  createSiteTemplate,
  getBookingSetup,
  getImageGenerationOffer,
  importOwnPageTemplate,
  listSiteTemplates,
  materializeTemplatePhoto,
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
  initiateMediaUpload,
  listMediaAssets,
  listPageTranslations,
  listPageVersions,
  restorePageVersion,
  requestImageGeneration,
  savePageDraft,
  savePageTranslation,
  setPageType,
} = vi.hoisted(() => ({
  completeMediaUpload: vi.fn(),
  createSiteTemplate: vi.fn(),
  getBookingSetup: vi.fn(),
  importOwnPageTemplate: vi.fn(),
  listSiteTemplates: vi.fn(),
  getImageGenerationOffer: vi.fn(),
  materializeTemplatePhoto: vi.fn(),
  getPageDraft: vi.fn(),
  getPageDraftPreview: vi.fn(),
  importPageTemplate: vi.fn(),
  initiateMediaUpload: vi.fn(),
  listMediaAssets: vi.fn(),
  listPageTranslations: vi.fn(),
  listPageVersions: vi.fn(),
  restorePageVersion: vi.fn(),
  requestImageGeneration: vi.fn(),
  savePageDraft: vi.fn(),
  savePageTranslation: vi.fn(),
  setPageType: vi.fn(),
}));

// Core's library opens on all trades; a product may set its own
// (`siteIndustry`, section-library-industry.test.tsx). Pinned here so a
// product's slot does not change what these tests count.
vi.mock("../../../product", () => ({ product: {} }));
// Image generation is a module of its own; a deployment without it has no
// offer to ask for (UX-041).
const composed = vi.hoisted(() => ({ imageGeneration: true }));
vi.mock("../../../generated/deployment", async (importOriginal) => {
  const { deployment } =
    await importOriginal<typeof import("../../../generated/deployment")>();
  return {
    deployment: {
      ...deployment,
      get modules() {
        return [
          ...deployment.modules,
          ...(composed.imageGeneration ? ["shared.image-generation"] : []),
        ];
      },
    },
  };
});

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  completeMediaUpload,
  createSiteTemplate,
  getBookingSetup,
  importOwnPageTemplate,
  listSiteTemplates,
  getImageGenerationOffer,
  materializeTemplatePhoto,
  getMediaAssetPreview: vi
    .fn()
    .mockRejectedValue(new Error("Unavailable fixture preview")),
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
  initiateMediaUpload,
  listMediaAssets,
  listPageTranslations,
  listPageVersions,
  restorePageVersion,
  requestImageGeneration,
  savePageDraft,
  savePageTranslation,
  setPageType,
  // The settings dialog's search preview stays loading unless a test asks.
  readSeoPreview: vi.fn(() => new Promise(() => undefined)),
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
const draft = {
  page_id: page.id,
  version: 1,
  draft_id: page.current_draft_id,
  content_hash: page.current_draft_hash,
  created_at: "2026-08-11T12:00:00Z",
  blocks: [
    {
      id: "019ff20d-a000-7000-8000-000000000022",
      position: 0,
      block_type: "core.hero",
      schema_version: 1,
      data: { heading: "Stary nagłówek", body: "Opis hero" },
    },
  ],
  media_asset_ids: [],
};
const translation = {
  id: "019ff20d-a000-7000-8000-000000000023",
  page_id: page.id,
  site_id: page.site_id,
  locale: "pl",
  slug: "start",
  title: "Start",
  description: "Opis",
  social_title: "",
  social_description: "",
  allow_title_fallback: false,
  allow_description_fallback: false,
  allow_social_title_fallback: false,
  allow_social_description_fallback: false,
  version: 1,
  slug_locked: false,
  created_at: "2026-08-11T12:00:00Z",
  updated_at: "2026-08-11T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  composed.imageGeneration = true;
  listSiteTemplates.mockResolvedValue({ items: [], limit: null });
  // A company without bookings, unless a test gives it an offer.
  getBookingSetup.mockRejectedValue(new Error("no bookings"));
  getImageGenerationOffer.mockResolvedValue({ ...offer, available: false });
  materializeTemplatePhoto.mockResolvedValue({
    asset_id: "019ff20d-a000-7000-8000-000000000099",
  });
  getPageDraft.mockResolvedValue(draft);
  getPageDraftPreview.mockResolvedValue(draft);
  listPageTranslations.mockResolvedValue({
    page_id: page.id,
    default_locale: "pl",
    supported_locales: ["pl", "en"],
    items: [translation],
  });
  listMediaAssets.mockResolvedValue({ items: [], next_cursor: null });
  importPageTemplate.mockResolvedValue({
    ...draft,
    version: 2,
    draft_id: "019ff20d-a000-7000-8000-000000000025",
    blocks: [
      {
        ...draft.blocks[0],
        schema_version: 2,
        data: {
          title: "Twoje imię i to, w czym pomagasz",
          text: "Przykładowa treść",
        },
      },
      {
        id: "019ff20d-a000-7000-8000-000000000026",
        position: 1,
        block_type: "core.rich_text",
        schema_version: 1,
        data: { text: "Kilka zdań o sobie" },
      },
      {
        id: "019ff20d-a000-7000-8000-000000000027",
        position: 2,
        block_type: "core.contact",
        schema_version: 1,
        data: { title: "Kontakt", email: "kontakt@example.com" },
      },
    ],
  });
  savePageDraft.mockResolvedValue({
    ...draft,
    version: 2,
    draft_id: "019ff20d-a000-7000-8000-000000000024",
    blocks: [
      {
        ...draft.blocks[0],
        schema_version: 5,
        data: { title: "Nowy nagłówek", text: "Opis hero" },
      },
    ],
  });
  savePageTranslation.mockResolvedValue({ ...translation, version: 2 });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("migruje hero v1 i zapisuje nową wersję draftu przez aktualny kontrakt", async () => {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged);

  const heading = await screen.findByLabelText("Nagłówek");
  expect((heading as HTMLInputElement).value).toBe("Stary nagłówek");
  fireEvent.change(heading, { target: { value: "Nowy nagłówek" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[0]).toBe(page.id);
  expect(savePageDraft.mock.calls[0]?.[1]).toMatchObject({
    expected_version: 1,
    blocks: [
      {
        block_type: "core.hero",
        // Saved at the current contract version: the editor migrates a v1
        // draft on load, so what leaves the panel is always the latest.
        schema_version: heroVersion,
        data: { title: "Nowy nagłówek", text: "Opis hero" },
      },
    ],
  });
  expect(onChanged).toHaveBeenCalledOnce();
});

test("a saved draft says what follows for the other languages, until the next edit", async () => {
  const notice =
    "Zapisano. Po publikacji tłumaczenia (English) zaktualizują się same.";
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    false,
    {
      afterSaveNotice: notice,
    },
  );

  const heading = await screen.findByLabelText("Nagłówek");
  expect(screen.queryByText(notice)).toBeNull();
  fireEvent.change(heading, { target: { value: "Nowy nagłówek" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  expect((await screen.findByText(notice)).getAttribute("role")).toBe("status");
  fireEvent.change(heading, { target: { value: "Jeszcze nowszy" } });
  await waitFor(() => expect(screen.queryByText(notice)).toBeNull());
});

test("bez modułu generowania obrazów edytor nie pyta o jego ofertę (UX-041)", async () => {
  composed.imageGeneration = false;
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  expect(await screen.findByLabelText("Treść")).not.toBeNull();
  expect(getImageGenerationOffer).not.toHaveBeenCalled();
});

test("odrzuca tekst hero dłuższy niż kanoniczny limit bloku, bez wysyłki", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  const text = await screen.findByLabelText("Treść");
  // core.hero.v2 caps `text` at 600; core.rich_text.v1 allows 10 000. The form
  // used to apply the larger limit to both, so the backend rejected a draft the
  // panel had accepted.
  fireEvent.change(text, { target: { value: "x".repeat(601) } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  expect(
    await screen.findByText("Tekst jest za długi dla tej sekcji."),
  ).not.toBeNull();
  expect(savePageDraft).not.toHaveBeenCalled();

  fireEvent.change(text, { target: { value: "x".repeat(600) } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
});

test("dodaje sekcję z powtarzalną listą i zapisuje jej wpisy", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  // The catalogue drives the picker, so a block added to the manifest is
  // offered here without the editor knowing its name.
  const picker = await screen.findByRole("combobox", { name: "Rodzaj sekcji" });
  picker.focus();
  fireEvent.change(picker, { target: { value: "Pytania" } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  fireEvent.click(
    await screen.findByRole("option", { name: "Pytania i odpowiedzi" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));

  fireEvent.click(await screen.findByRole("button", { name: "Dodaj pozycję" }));
  fireEvent.change(await screen.findByLabelText("Pytanie"), {
    target: { value: "Ile trwa wizyta?" },
  });
  fireEvent.change(screen.getByLabelText("Odpowiedź"), {
    target: { value: "Około godziny." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[1].blocks[1]).toEqual({
    block_type: "core.faq",
    schema_version: 3,
    // `title` was left blank and is optional, so it is absent rather than "".
    data: {
      layout: "classic",
      items: [{ question: "Ile trwa wizyta?", answer: "Około godziny." }],
    },
  });
});

test("stay blocks are offered to a company that has an offer booked from–to, and to no other", async () => {
  const options = async () => {
    const picker = await screen.findByRole("combobox", {
      name: "Rodzaj sekcji",
    });
    picker.focus();
    fireEvent.change(picker, { target: { value: "Mapa" } });
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    return screen.queryAllByRole("option").map((item) => item.textContent);
  };
  // Visits only: nothing of stays among the kinds of section.
  getBookingSetup.mockResolvedValue({
    services: [{ time_model: "slot", active: true }],
    resources: [],
  });
  const first = renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
  );
  await waitFor(() => expect(getBookingSetup).toHaveBeenCalled());
  expect(await options()).not.toContain("Mapa położenia");
  first.unmount();

  getBookingSetup.mockResolvedValue({
    services: [{ time_model: "range", active: true }],
    resources: [],
  });
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await waitFor(async () =>
    expect(await options()).toContain("Mapa położenia"),
  );
});

test("przestawia pozycje listy strzałkami i zapisuje nową kolejność", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  const picker = await screen.findByRole("combobox", { name: "Rodzaj sekcji" });
  picker.focus();
  fireEvent.change(picker, { target: { value: "Pytania" } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  fireEvent.click(
    await screen.findByRole("option", { name: "Pytania i odpowiedzi" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));

  for (const question of ["Pierwsze?", "Drugie?"]) {
    fireEvent.click(
      await screen.findByRole("button", { name: "Dodaj pozycję" }),
    );
    const fields = await screen.findAllByLabelText("Pytanie");
    fireEvent.change(fields.at(-1)!, { target: { value: question } });
    fireEvent.change(screen.getAllByLabelText("Odpowiedź").at(-1)!, {
      target: { value: "Tak." },
    });
  }
  const up = screen.getAllByRole("button", { name: "Przesuń pozycję wyżej" });
  const down = screen.getAllByRole("button", {
    name: "Przesuń pozycję niżej",
  });
  expect(up[0]).toBeDisabled();
  expect(down[1]).toBeDisabled();
  fireEvent.click(up[1]!);
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(
    savePageDraft.mock.calls[0]?.[1].blocks[1].data.items.map(
      (item: { question: string }) => item.question,
    ),
  ).toEqual(["Drugie?", "Pierwsze?"]);
});

test("importuje szablon do wersjonowanego draftu przez API", async () => {
  getPageDraft.mockResolvedValue({ ...draft, blocks: [] });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged, true);

  // An empty page offers templates instead of a bare "no sections" message.
  await screen.findByRole("img", {
    name: `Miniatura szablonu ${firstTemplate.labels.pl.name}`,
  });
  const templateButton = templateUseButton(firstTemplate.labels.pl.name);
  const emptyCanvas = screen.getByTestId("live-canvas");
  fireEvent.click(templateButton);

  expect(await screen.findByDisplayValue(/Twoje imię/)).not.toBeNull();
  // The whole page came from the server: the canvas is drawn afresh.
  expect(screen.getByTestId("live-canvas")).not.toBe(emptyCanvas);
  expect(importPageTemplate).toHaveBeenCalledOnce();
  expect(importPageTemplate.mock.calls[0]?.[0]).toBe(page.id);
  expect(importPageTemplate.mock.calls[0]?.[1]).toEqual({
    expected_version: 1,
    template_id: firstTemplate.id,
    template_version: firstTemplate.version,
    locale: "pl",
  });
  expect(savePageDraft).not.toHaveBeenCalled();
  expect(onChanged).toHaveBeenCalledOnce();
});

test.each([
  {
    locale: "pl" as const,
    messages: polishMessages,
    thumbnail: `Miniatura szablonu ${firstTemplate.labels.pl.name}`,
    previewButton: "Podgląd",
    previewTitle: `Podgląd szablonu ${firstTemplate.labels.pl.name}`,
  },
  {
    locale: "en" as const,
    messages: englishMessages,
    thumbnail: `Thumbnail of the ${firstTemplate.labels.en.name} template`,
    previewButton: "Preview",
    previewTitle: `Preview of the ${firstTemplate.labels.en.name} template`,
  },
])(
  "pokazuje lokalizowaną miniaturę i dostępny preview w $locale",
  async ({ locale, messages, previewButton, previewTitle, thumbnail }) => {
    getPageDraft.mockResolvedValue({ ...draft, blocks: [] });
    renderEditor(locale, messages, vi.fn().mockResolvedValue(undefined), true);

    const thumbnailElement = await screen.findByRole("img", {
      name: thumbnail,
    });
    const templateGrid = thumbnailElement.closest("ul");
    expect(templateGrid).not.toBeNull();
    expect(within(templateGrid!).getAllByRole("img")).toHaveLength(
      offeredTemplates.length,
    );

    // The gallery's tile opens the template's details, with its preview.
    fireEvent.click(within(templateGrid!).getAllByRole("button")[0]!);
    const trigger = screen.getByRole("button", { name: previewButton });
    trigger.focus();
    fireEvent.click(trigger);

    expect(
      await screen.findByRole("dialog", { name: previewTitle }),
    ).not.toBeNull();
    const result = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
  },
  // Every offered recipe renders a scaled preview: nine since phase 3b,
  // slow under a full test run on the dev VPS.
  45_000,
);

test("a ready page's details list its sections and the way back returns to its tile", async () => {
  getPageDraft.mockResolvedValue({ ...draft, blocks: [] });
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  const name = firstTemplate.labels.pl.name;
  const studio = polishMessages.Sites.studio;
  await screen.findByRole("img", { name: `Miniatura szablonu ${name}` });
  const tile = () =>
    screen.getByRole("button", {
      name: (accessible) => accessible.startsWith(name),
    });
  fireEvent.click(tile());
  expect(
    screen.getByRole("button", { name: studio.allTemplates }),
  ).toHaveFocus();
  expect(screen.getByRole("heading", { name })).toBeDefined();
  const count = firstTemplate.blocks.length;
  const sections = screen.getByRole("list", {
    name: new RegExp(`^Zawiera ${count} sekcj`),
  });
  expect(within(sections).getAllByRole("listitem")).toHaveLength(count);
  expect(
    screen.getByRole("button", { name: `Użyj szablonu ${name}` }),
  ).toBeDefined();
  const rail = screen.getByRole("complementary", {
    name: studio.pageNavigation,
  });
  expect(
    (await axe.run(rail, { rules: { "color-contrast": { enabled: false } } }))
      .violations,
  ).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: studio.allTemplates }));
  await waitFor(() => expect(tile()).toHaveFocus());
  expect(importPageTemplate).not.toHaveBeenCalled();
});

test("nie wysyła sekcji FAQ bez ani jednego wpisu", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  const picker = await screen.findByRole("combobox", { name: "Rodzaj sekcji" });
  picker.focus();
  fireEvent.change(picker, { target: { value: "Pytania" } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  fireEvent.click(
    await screen.findByRole("option", { name: "Pytania i odpowiedzi" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  expect(await screen.findByText("To pole jest wymagane.")).toHaveAttribute(
    "role",
    "alert",
  );
  expect(savePageDraft).not.toHaveBeenCalled();
});

test("pokazuje konflikt optimistic lock bez nadpisania lokalnych wartości", async () => {
  savePageDraft.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "draft_version_conflict",
      detail: "Draft changed",
      correlation_id: null,
    }),
  );
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  const heading = await screen.findByLabelText("Nagłówek");
  fireEvent.change(heading, { target: { value: "Moja lokalna wersja" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  expect(
    await screen.findByText(/Ktoś zapisał w międzyczasie nowszą wersję szkicu/),
  ).not.toBeNull();
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Moja lokalna wersja",
  );
  expect(screen.getByRole("button", { name: "Zapisz stronę" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Wczytaj zapisaną wersję" }),
  ).toHaveFocus();
});

test("pobiera jawną wersję i renderuje chroniony preview", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));

  const previewButton = await screen.findByRole("button", {
    name: "Protected preview",
  });
  fireEvent.click(previewButton);

  await waitFor(() =>
    expect(getPageDraftPreview).toHaveBeenCalledWith(page.id, draft.draft_id),
  );
  expect(await screen.findByTestId("draft-preview")).not.toBeNull();
  expect(
    screen.getByRole("heading", { name: "Stary nagłówek" }),
  ).not.toBeNull();

  const viewport = screen.getByTestId("draft-preview-viewport");
  expect(viewport).toHaveAttribute("data-viewport", "desktop");
  fireEvent.click(screen.getByRole("button", { name: "Phone" }));
  expect(viewport).toHaveAttribute("data-viewport", "mobile");
  expect(viewport).toHaveStyle({ width: "390px" });
});

test("the top bar names the draft and resizes the canvas from its middle", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  const canvas = await screen.findByTestId("live-canvas");
  expect(await screen.findByText("Szkic, wersja 1")).toBeDefined();
  const devices = screen.getByRole("group", { name: "Rozmiar podglądu" });
  expect(
    within(devices).getByRole("button", { name: "Komputer" }),
  ).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(devices).getByRole("button", { name: "Telefon" }));
  expect(canvas).toHaveAttribute("data-viewport", "mobile");
  expect(canvas).toHaveStyle({ width: "390px" });
  expect(
    within(devices).getByRole("button", { name: "Telefon" }),
  ).toHaveAttribute("aria-pressed", "true");
  // The forms have no canvas to resize.
  fireEvent.click(screen.getByRole("button", { name: "Formularze" }));
  expect(screen.queryByRole("group", { name: "Rozmiar podglądu" })).toBeNull();
});

test("the page list's preview opens the saved draft once it is loaded", async () => {
  renderEditor(
    "en",
    englishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
    { previewOnOpen: true },
  );

  expect(await screen.findByTestId("draft-preview")).not.toBeNull();
  expect(getPageDraftPreview).toHaveBeenCalledOnce();
  expect(getPageDraftPreview).toHaveBeenCalledWith(page.id, draft.draft_id);
});

test("zapisuje metadane EN bez zapożyczeń ze źródła i z optimistic lockiem", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");

  await fromMore("Page settings", "More");
  const localeSelect = screen.getByRole("combobox", { name: "Language" });
  fireEvent.click(localeSelect);
  const englishOption = await screen.findByRole("option", { name: "English" });
  fireEvent.pointerDown(englishOption, { button: 0 });
  fireEvent.pointerUp(englishOption, { button: 0 });
  fireEvent.click(englishOption);
  // A version with its own body has its own words (TL15): nothing to borrow.
  await waitFor(() =>
    expect(screen.getByLabelText("Page title")).not.toBeNull(),
  );
  expect(screen.queryByRole("checkbox", { name: /Allow fallback/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("Page title"), {
    target: { value: "English home" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save metadata" }));

  await waitFor(() => expect(savePageTranslation).toHaveBeenCalledOnce());
  expect(savePageTranslation.mock.calls[0]?.slice(0, 3)).toEqual([
    page.id,
    "en",
    expect.objectContaining({
      slug: "home",
      title: "English home",
      allow_title_fallback: false,
      allow_description_fallback: false,
      allow_social_title_fallback: false,
      allow_social_description_fallback: false,
      expected_version: 0,
    }),
  ]);
});

test("the page settings show what a search engine reads, again after a save", async () => {
  const { readSeoPreview } = await import("@saas-core/api-client");
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");

  await fromMore("Ustawienia strony");
  expect(
    await screen.findByRole("heading", { name: "Podgląd w wyszukiwarce" }),
  ).not.toBeNull();
  await waitFor(() =>
    expect(readSeoPreview).toHaveBeenCalledWith(page.site_id, page.id, "pl"),
  );
  const before = vi.mocked(readSeoPreview).mock.calls.length;
  // The language reads as its name before the list is ever opened, not „pl”.
  expect(screen.getByRole("combobox", { name: "Język" })).toHaveTextContent(
    "Polski",
  );

  fireEvent.change(screen.getByLabelText("Tytuł strony"), {
    target: { value: "Nowy tytuł" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adres i opis" }));
  await waitFor(() => expect(savePageTranslation).toHaveBeenCalledOnce());
  // The saved metadata is what the preview reads next.
  await waitFor(() =>
    expect(vi.mocked(readSeoPreview).mock.calls.length).toBeGreaterThan(before),
  );
});

test("konflikt metadanych zachowuje lokalną wartość", async () => {
  savePageTranslation.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "translation_version_conflict",
      detail: "Translation changed",
      correlation_id: null,
    }),
  );
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");

  await fromMore("Ustawienia strony");
  fireEvent.change(screen.getByLabelText("Tytuł strony"), {
    target: { value: "Moja lokalna metadata" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adres i opis" }));

  expect(
    await screen.findByText(/Ktoś zapisał w międzyczasie nowsze dane/),
  ).not.toBeNull();
  expect(
    (screen.getByLabelText("Tytuł strony") as HTMLInputElement).value,
  ).toBe("Moja lokalna metadata");
  expect(
    screen.getByRole("button", { name: "Zapisz adres i opis" }),
  ).toBeDisabled();
});

test("the page's settings mark what it is without changing how it looks", async () => {
  setPageType.mockResolvedValue({ ...page, page_type: "contact" });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged);
  await screen.findByLabelText("Nagłówek");

  await fromMore("Ustawienia strony");
  fireEvent.change(await screen.findByLabelText("Rodzaj podstrony"), {
    target: { value: "contact" },
  });

  await waitFor(() =>
    expect(setPageType).toHaveBeenCalledWith(page.id, "contact"),
  );
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  // Said plainly, because a control that looks like a layout switch and is
  // not would be worse than no control.
  expect(screen.getByText(/Nie zmienia wyglądu strony/)).not.toBeNull();
});

test("przesyła obraz przez signed PUT i odświeża listę mediów", async () => {
  const pendingAsset = {
    id: "019ff20d-a000-7000-8000-000000000030",
    original_filename: "hero.png",
    content_type: "image/png",
    size: 12,
    state: "pending",
    variants: {},
    rejection_reason: "",
    created_at: "2026-08-11T12:00:00Z",
    updated_at: "2026-08-11T12:00:00Z",
  };
  initiateMediaUpload.mockResolvedValue({
    asset: pendingAsset,
    upload_url: "https://storage.example.test/signed",
    upload_headers: { "content-type": "image/png" },
    expires_at: "2026-08-11T12:10:00Z",
  });
  completeMediaUpload.mockResolvedValue({
    ...pendingAsset,
    state: "uploaded",
  });
  listMediaAssets
    .mockResolvedValueOnce({ items: [], next_cursor: null })
    .mockResolvedValueOnce({
      items: [{ ...pendingAsset, state: "uploaded" }],
      next_cursor: null,
    });
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
  vi.stubGlobal("fetch", fetchMock);
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");

  await fromMore(polishMessages.Sites.media);
  const file = new File([new Uint8Array(12)], "hero.png", {
    type: "image/png",
  });
  fireEvent.change(screen.getByLabelText("Prześlij obraz"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Prześlij" }));

  await waitFor(() =>
    expect(completeMediaUpload).toHaveBeenCalledWith(pendingAsset.id),
  );
  expect(initiateMediaUpload).toHaveBeenCalledWith(
    { filename: "hero.png", content_type: "image/png", size: 12 },
    expect.any(String),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "https://storage.example.test/signed",
    expect.objectContaining({ method: "PUT", body: file }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("uploaded");
  expect(listMediaAssets).toHaveBeenCalledTimes(2);
});

test("historia pokazuje autora i przekazuje wybraną publikację do rollbacku", async () => {
  const onRollback = vi.fn();
  const publication = {
    id: "019ff20d-a000-7000-8000-000000000025",
    site_id: page.site_id,
    sequence: 2,
    snapshot_schema_version: 1,
    snapshot_hash: "b".repeat(64),
    source_publication_id: "019ff20d-a000-7000-8000-000000000026",
    reason: "rollback" as const,
    created_by: {
      id: "019ff20d-a000-7000-8000-000000000027",
      email: "owner@example.test",
      name: "",
    },
    created_at: "2026-08-11T12:00:00Z",
  };
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PublicationHistory
        currentPublicationId="019ff20d-a000-7000-8000-000000000099"
        loading={false}
        onRollback={onRollback}
        publications={[publication]}
      />
    </NextIntlClientProvider>,
  );

  expect(screen.getByText(/owner@example\.test/)).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: /Działania dla publikacji/ }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", {
      name: "Przywróć jako nową publikację",
    }),
  );
  expect(onRollback).toHaveBeenCalledWith(publication);
});

test("edytor PL nie ma automatycznie wykrywalnych naruszeń axe", async () => {
  const rendered = renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
  );
  await screen.findByLabelText("Nagłówek");

  const result = await axe.run(rendered.container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

/** A ready page opens from its tile; "use" is in its details. */
function templateUseButton(name: string, locale: "pl" | "en" = "pl") {
  const use =
    locale === "pl" ? `Użyj szablonu ${name}` : `Use the ${name} template`;
  const shown = screen.queryByRole("button", { name: use });
  if (shown) return shown;
  fireEvent.click(
    screen.getByRole("button", {
      name: (accessible) => accessible.startsWith(name),
    }),
  );
  return screen.getByRole("button", { name: use });
}

/** „Więcej” holds the page's settings, files and history (UX-039). */
async function fromMore(item: string, more = "Więcej") {
  fireEvent.click(screen.getByRole("button", { name: more }));
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
}

function renderEditor(
  locale: "pl" | "en",
  messages: typeof polishMessages | typeof englishMessages,
  onChanged: () => Promise<void>,
  visual = false,
  extraProps: Pick<
    ComponentProps<typeof PageEditor>,
    | "appearance"
    | "appearanceControls"
    | "onExitStateChange"
    | "previewOnOpen"
    | "afterSaveNotice"
  > = {},
) {
  const result = render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Europe/Warsaw"
    >
      <PageEditor {...extraProps} onChanged={onChanged} page={page} />
    </NextIntlClientProvider>,
  );
  if (!visual)
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "pl" ? "Formularze" : "Forms",
      }),
    );
  return result;
}

test("biblioteka filtruje branżę, zachowuje bazę i zapisuje wybraną sekcję", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Biblioteka sekcji" }));
  fireEvent.change(await screen.findByLabelText("Branża"), {
    target: { value: "medicine" },
  });
  expect(
    screen.getByRole("button", { name: "Dodaj: Klasyczna lista" }),
  ).toBeDefined();
  expect(
    screen.queryByRole("button", { name: "Dodaj: Obszary obsługi" }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj: Ścieżka konsultacji" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Zapisz stronę" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[1].blocks[1]).toMatchObject({
    block_type: "core.feature_list",
    schema_version: 5,
    data: {
      layout: "care_path",
      items: [
        { title: "Przygotowanie" },
        { title: "Konsultacja" },
        { title: "Dalsze kroki" },
      ],
    },
  });
});

test("zmiana układu zachowuje tekst istniejącej sekcji", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");
  fireEvent.change(screen.getByLabelText("Układ sekcji"), {
    target: { value: "split" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[1].blocks[0]).toMatchObject({
    schema_version: heroVersion,
    data: { title: "Stary nagłówek", text: "Opis hero", layout: "split" },
  });
});

test("pola innego układu czekają, aż układ ich użyje, a wypełnione zostają widoczne", async () => {
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      {
        id: "019ff20d-a000-7000-8000-000000000022",
        position: 0,
        block_type: "core.feature_list",
        schema_version: 5,
        data: {
          title: "Oferta",
          layout: "cards",
          items: [{ title: "Pierwsza", note: "Uwaga do pierwszej" }],
        },
      },
    ],
  });
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");
  const sites = polishMessages.Sites;
  // Cards show no columns and no group: the inspector does not ask for them.
  expect(screen.queryByText(sites.featureColumns)).toBeNull();
  expect(screen.queryByLabelText(sites.itemGroup)).toBeNull();
  expect(screen.queryByLabelText(sites.itemValueFirst)).toBeNull();
  // A note already written stays editable, and the switch says it is hidden.
  expect(screen.getByLabelText(sites.itemNote)).toHaveValue(
    "Uwaga do pierwszej",
  );
  expect(screen.getByRole("status")).toHaveTextContent(sites.itemNote);
  fireEvent.change(screen.getByLabelText("Układ sekcji"), {
    target: { value: "scope_comparison" },
  });
  expect(await screen.findByText(sites.featureColumns)).toBeDefined();
  expect(screen.getByLabelText(sites.itemValueThird)).toBeDefined();
  expect(screen.getByLabelText(sites.itemGroup)).toBeDefined();
});

test("porównanie układów pokazuje własną treść w każdym układzie i zmienia dopiero po wyborze", async () => {
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      {
        id: "019ff20d-a000-7000-8000-000000000022",
        position: 0,
        block_type: "core.feature_list",
        schema_version: 5,
        data: {
          title: "Nasza oferta",
          layout: "cards",
          items: [{ title: "Pierwsza usługa", note: "Uwaga do usługi" }],
        },
      },
    ],
  });
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");
  const library = polishMessages.Sites.sectionLibrary;
  fireEvent.click(screen.getByRole("button", { name: library.compareLayouts }));
  const dialog = await screen.findByRole("dialog", {
    name: library.compareLayouts,
  });
  // Every layout is a card; the section's own title is in the miniatures.
  const cards = within(dialog).getAllByRole("listitem");
  expect(cards.length).toBeGreaterThan(20);
  expect(dialog.textContent).toContain("Nasza oferta");
  expect(within(dialog).getByText(library.currentLayout)).toBeDefined();
  // Before choosing, each card says what its layout would leave out.
  const steps = cards.find((card) =>
    within(card).queryByText("Instrukcja z uwagą przy kroku"),
  )!;
  expect(steps.textContent).toContain(library.layoutShowsAll);
  // Nothing changed yet: the select still says cards.
  expect(screen.getByLabelText("Układ sekcji")).toHaveValue("cards");
  fireEvent.click(
    within(steps).getByRole("button", {
      name: library.useLayoutNamed.replace(
        "{name}",
        "Instrukcja z uwagą przy kroku",
      ),
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByLabelText("Układ sekcji")).toHaveValue(
    "instruction_notes",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getByLabelText("Układ sekcji")).toHaveValue("cards");
});

test("historia wersji pokazuje pochodzenie, podgląd i przywraca wersję jako nową", async () => {
  const author = {
    id: "019ff20d-a000-7000-8000-0000000000e0",
    email: "ania@example.test",
  };
  listPageVersions.mockResolvedValue({
    items: [
      {
        id: draft.draft_id,
        number: 2,
        origin: "template",
        origin_ref: "core.step_guide@1",
        created_by: author,
        automation: false,
        block_count: 10,
        current: true,
        created_at: "2026-09-28T12:00:00Z",
      },
      {
        id: "019ff20d-a000-7000-8000-0000000000e1",
        number: 1,
        origin: "save",
        origin_ref: "",
        created_by: author,
        automation: false,
        block_count: 1,
        current: false,
        created_at: "2026-09-27T12:00:00Z",
      },
    ],
    next_cursor: null,
  });
  restorePageVersion.mockResolvedValue({
    ...draft,
    version: 3,
    draft_id: "019ff20d-a000-7000-8000-0000000000e2",
    blocks: [
      {
        ...draft.blocks[0],
        schema_version: heroVersion,
        data: { title: "Pierwsza wersja" },
      },
    ],
  });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged);
  await screen.findByLabelText("Nagłówek");
  const versions = polishMessages.Sites.versions;
  await fromMore(versions.open);
  const dialog = await screen.findByRole("dialog", { name: versions.title });
  expect(
    await within(dialog).findByText("Szablon: Poradnik krok po kroku"),
  ).toBeDefined();
  expect(within(dialog).getByText(versions.origin.save)).toBeDefined();
  // The current version is what the editor holds: nothing to restore.
  expect(
    within(dialog).queryByRole("button", { name: "Przywróć wersję 2" }),
  ).toBeNull();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Przywróć wersję 1" }),
  );
  expect(within(dialog).getByText("Przywrócić wersję 1?")).toBeDefined();
  // No unsaved edits: nothing to warn about.
  expect(within(dialog).queryByText(versions.confirmDirty)).toBeNull();
  const confirm = within(dialog).getAllByRole("button", {
    name: "Przywróć wersję 1",
  });
  fireEvent.click(confirm[0]!);
  await waitFor(() => expect(restorePageVersion).toHaveBeenCalledOnce());
  expect(restorePageVersion.mock.calls[0]?.slice(0, 3)).toEqual([
    page.id,
    "019ff20d-a000-7000-8000-0000000000e1",
    { expected_version: 1 },
  ]);
  expect(
    await screen.findByText("Przywrócono wersję 1 jako wersję 3."),
  ).toHaveAttribute("role", "status");
  expect(screen.getByLabelText("Nagłówek")).toHaveValue("Pierwsza wersja");
  expect(onChanged).toHaveBeenCalled();
  // The restore is a server boundary: nothing local to undo.
  expect(screen.getByRole("button", { name: "Cofnij" })).toBeDisabled();
});

test("biblioteka EN pokazuje opis, dostępny podgląd i angielską treść", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");
  fireEvent.click(screen.getByRole("button", { name: "Section library" }));
  // Editorial, quote and product families now share the first dozen cards.
  fireEvent.click(
    await screen.findByRole("button", { name: /^Show more templates/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Preview: Expandable FAQ" }),
  );
  const preview = screen.getByRole("region", { name: "Section preview" });
  expect(preview.textContent).toContain("How do I start?");
  const previewDialog = screen.getByRole("dialog", { name: "Expandable FAQ" });
  const result = await axe.run(previewDialog, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
  fireEvent.click(within(previewDialog).getByRole("button", { name: "Close" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("region", { name: "Section preview" }),
    ).toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add: Service cards" }));
  expect(
    (screen.getAllByLabelText("Heading")[1] as HTMLInputElement).value,
  ).toBe("From idea to a working solution");
});

test("visual canvas follows edits, undo/redo and section duplication without saving", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  const heading = await screen.findByLabelText("Nagłówek");
  expect(
    (screen.getByRole("button", { name: "Cofnij" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.change(heading, { target: { value: "Treść na żywo" } });
  expect(screen.getByTestId("live-canvas").textContent).toContain(
    "Treść na żywo",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getByTestId("live-canvas").textContent).toContain(
    "Stary nagłówek",
  );
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  expect(screen.getByTestId("live-canvas").textContent).toContain(
    "Treść na żywo",
  );
  fireEvent.click(screen.getByRole("button", { name: "Powiel sekcję" }));
  expect(screen.getAllByRole("button", { name: /Edytuj sekcję/ })).toHaveLength(
    2,
  );
  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Druga sekcja" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Edytuj sekcję 1:/ }));
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Treść na żywo",
  );
  expect(savePageDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getAllByRole("button", { name: /Edytuj sekcję/ })).toHaveLength(
    1,
  );
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  expect(screen.getAllByRole("button", { name: /Edytuj sekcję/ })).toHaveLength(
    2,
  );
});

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "visual editor is accessible in %s and handles incomplete content",
  async (locale, messages) => {
    const result = renderEditor(
      locale,
      messages,
      vi.fn().mockResolvedValue(undefined),
      true,
    );
    const heading = await screen.findByLabelText(
      locale === "pl" ? "Nagłówek" : "Heading",
    );
    expect(
      (
        await axe.run(result.container, {
          rules: { "color-contrast": { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
    fireEvent.change(heading, { target: { value: "" } });
    expect(screen.getByTestId("live-canvas").textContent).toContain(
      messages.Sites.studio.incomplete,
    );
    expect(
      (
        await axe.run(result.container, {
          rules: { "color-contrast": { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  },
);

test("moving a section by keyboard follows its inspector and is one undo step", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Powiel sekcję" }));
  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Druga sekcja" },
  });
  fireEvent.keyDown(screen.getByRole("button", { name: "Przenieś sekcję 2" }), {
    key: "ArrowUp",
  });
  expect(
    screen.getByTestId("live-canvas").querySelector("h1")?.textContent,
  ).toBe("Druga sekcja");
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Druga sekcja",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(
    screen.getByTestId("live-canvas").querySelector("h1")?.textContent,
  ).toBe("Stary nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(
    savePageDraft.mock.calls[0]?.[1].blocks.map(
      (block: { data: { title: string } }) => block.data.title,
    ),
  ).toEqual(["Druga sekcja", "Stary nagłówek"]);
});

test("the outline moves a section by its own handle, between the site's header and footer", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
    {
      appearance: parseSiteAppearance({
        schemaVersion: 1,
        designTokens: {
          schemaVersion: 1,
          palette: "neutral",
          typography: "sans",
          radius: "medium",
          spacing: "comfortable",
        },
        font: "system",
        width: "standard",
        buttons: "solid",
        header: { layout: "classic", brand: "Gabinet", tagline: "" },
        footer: { layout: "simple", text: "Zapraszamy", links: [] },
        navigation: { mobile: "drawer", tablet: "drawer" },
      }),
    },
  );
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Powiel sekcję" }));
  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Druga sekcja" },
  });
  const rail = screen.getByRole("complementary", { name: "Budowa strony" });
  const rows = within(rail).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rail).getByText("Nagłówek strony")).toBeDefined();
  expect(within(rail).getByText("Stopka strony")).toBeDefined();
  fireEvent.keyDown(
    within(rail).getByRole("button", { name: "Przenieś sekcję 2 na liście" }),
    { key: "ArrowUp" },
  );
  expect(
    screen.getByTestId("live-canvas").querySelector("h1")?.textContent,
  ).toBe("Druga sekcja");
  expect(
    within(rail).getByRole("button", { name: /Druga sekcja/ }),
  ).toHaveAttribute("aria-current", "true");
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(
    screen.getByTestId("live-canvas").querySelector("h1")?.textContent,
  ).toBe("Stary nagłówek");
  expect(savePageDraft).not.toHaveBeenCalled();
});

test("the inspector names the section's place, keeps its icons beside the name and shows one part at a time", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const t = polishMessages.Sites;
  fireEvent.click(screen.getByRole("button", { name: t.studio.duplicate }));
  const inspector = screen.getByRole("complementary", {
    name: t.studio.inspector,
  });
  expect(within(inspector).getByText("Sekcja 2 z 2")).toBeDefined();
  for (const name of [
    t.moveBlockUp,
    t.moveBlockDown,
    t.studio.duplicate,
    t.ownTemplates.saveSection,
    t.removeBlock,
  ])
    expect(within(inspector).getByRole("button", { name })).toBeDefined();
  const tab = (name: string) => within(inspector).getByRole("tab", { name });
  expect(tab(t.studio.tabContent)).toHaveAttribute("aria-selected", "true");
  expect(
    within(inspector).getByRole("textbox", { name: "Nagłówek" }),
  ).toBeDefined();
  expect(
    within(inspector).queryByRole("combobox", {
      name: t.sectionLibrary.layout,
    }),
  ).toBeNull();
  fireEvent.click(tab(t.studio.tabLayout));
  expect(
    within(inspector).getByRole("combobox", { name: t.sectionLibrary.layout }),
  ).toBeDefined();
  expect(
    within(inspector).queryByRole("textbox", { name: "Nagłówek" }),
  ).toBeNull();
  fireEvent.click(tab(t.studio.tabStyle));
  expect(
    within(inspector).getByRole("group", {
      name: t.sectionPresentation.fields.inner,
    }),
  ).toBeDefined();
  expect(
    (
      await axe.run(inspector, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

test("a save the content refuses takes the inspector back to that content", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const t = polishMessages.Sites;
  const inspector = screen.getByRole("complementary", {
    name: t.studio.inspector,
  });
  fireEvent.click(
    within(inspector).getByRole("tab", { name: t.studio.tabStyle }),
  );
  // The heading's field is mounted, only hidden, while "Styl" is shown.
  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: t.studio.save }));
  await waitFor(() =>
    expect(
      within(inspector).getByRole("tab", { name: t.studio.tabContent }),
    ).toHaveAttribute("aria-selected", "true"),
  );
  await waitFor(() =>
    expect(
      within(inspector).getByRole("textbox", { name: "Nagłówek" }),
    ).toHaveFocus(),
  );
  expect(savePageDraft).not.toHaveBeenCalled();
});

test("inline text commits to the existing form, cancels and undoes without submitting", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const label = "Edytuj na podglądzie: Nagłówek";
  fireEvent.click(screen.getByRole("button", { name: label }));
  fireEvent.change(screen.getByRole("textbox", { name: label }), {
    target: { value: "<b>Tekst dosłowny</b>" },
  });
  fireEvent.keyDown(screen.getByRole("textbox", { name: label }), {
    key: "Enter",
  });
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "<b>Tekst dosłowny</b>",
  );
  expect(screen.getByTestId("live-canvas").querySelector("b")).toBeNull();
  expect(savePageDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: label }));
  fireEvent.change(screen.getByRole("textbox", { name: label }), {
    target: { value: "Anulowana zmiana" },
  });
  fireEvent.keyDown(screen.getByRole("textbox", { name: label }), {
    key: "Escape",
  });
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "<b>Tekst dosłowny</b>",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Stary nagłówek",
  );
  fireEvent.click(screen.getByRole("button", { name: label }));
  fireEvent.change(screen.getByRole("textbox", { name: label }), {
    target: { value: "" },
  });
  fireEvent.keyDown(screen.getByRole("textbox", { name: label }), {
    key: "Enter",
  });
  await waitFor(() => expect(screen.getByLabelText("Nagłówek")).toHaveFocus());
  expect(screen.getByTestId("live-canvas").textContent).toContain(
    polishMessages.Sites.studio.incomplete,
  );
});

test("inline list editing addresses the selected item even when titles are identical", async () => {
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      {
        ...draft.blocks[0],
        block_type: "core.feature_list",
        schema_version: 2,
        data: {
          layout: "cards",
          title: "Oferta",
          items: [
            { title: "Ta sama nazwa", text: "Pierwsza" },
            { title: "Ta sama nazwa", text: "Druga" },
          ],
        },
      },
    ],
  });
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  const controls = await screen.findAllByRole("button", {
    name: "Edytuj na podglądzie: Nazwa pozycji",
  });
  fireEvent.click(controls[1]);
  const input = screen.getByRole("textbox", {
    name: "Edytuj na podglądzie: Nazwa pozycji",
  });
  fireEvent.change(input, { target: { value: "Zmieniona druga pozycja" } });
  fireEvent.blur(input);
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[1].blocks[0].data).toEqual({
    layout: "cards",
    title: "Oferta",
    items: [
      { title: "Ta sama nazwa", text: "Pierwsza" },
      { title: "Zmieniona druga pozycja", text: "Druga" },
    ],
  });
});

test("the contextual library inserts between sections and undo restores the original order", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Powiel sekcję" }));
  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Ostatnia sekcja" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Edytuj sekcję 1:/ }));
  // The panel's library puts it under the selected section.
  fireEvent.click(screen.getByRole("button", { name: "Biblioteka sekcji" }));
  expect(
    screen.getByText(
      polishMessages.Sites.studio.insertAfterNumber.replace("{number}", "1"),
    ),
  ).toBeDefined();
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj: Klasyczna lista" }),
  );
  expect(screen.getAllByRole("button", { name: /Edytuj sekcję/ })).toHaveLength(
    3,
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getAllByRole("button", { name: /Edytuj sekcję/ })).toHaveLength(
    2,
  );
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(
    savePageDraft.mock.calls[0]?.[1].blocks.map(
      (block: { block_type: string }) => block.block_type,
    ),
  ).toEqual(["core.hero", "core.feature_list", "core.hero"]);
  expect(savePageDraft.mock.calls[0]?.[1].blocks[2].data.title).toBe(
    "Ostatnia sekcja",
  );
});

test("the canvas's + inserts above the first section and at the end, each one undo step", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const studio = polishMessages.Sites.studio;
  fireEvent.click(
    screen.getByRole("button", {
      name: studio.insertBefore.replace("{number}", "1"),
    }),
  );
  // The library opens beside the canvas, aimed at that gap, not in a dialog.
  const rail = screen.getByRole("complementary", {
    name: studio.pageNavigation,
  });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(within(rail).getByText(studio.insertAtStart)).toBeDefined();
  await waitFor(() =>
    expect(
      within(rail).getByRole("searchbox", {
        name: polishMessages.Sites.sectionLibrary.search,
      }),
    ).toHaveFocus(),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj: Klasyczna lista" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  // Added, the library goes back to "under the selected section": the new one.
  expect(
    within(rail).getByText(studio.insertAfterNumber.replace("{number}", "1")),
  ).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: studio.insertAtEnd }));
  expect(
    within(rail).getByText(studio.insertAfterNumber.replace("{number}", "2")),
  ).toBeDefined();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Dodaj: Klasyczne FAQ",
    }),
  );
  const sections = () =>
    screen
      .getAllByRole("button", { name: /Edytuj sekcję/ })
      .map((button) => button.getAttribute("aria-label"));
  await waitFor(() => expect(sections()).toHaveLength(3));
  expect(sections()[0]).toMatch(/^Edytuj sekcję 1: Oferta/);
  expect(sections()[1]).toMatch(/^Edytuj sekcję 2: Baner powitalny/);
  expect(sections()[2]).toMatch(/^Edytuj sekcję 3: Pytania i odpowiedzi/);
  fireEvent.click(screen.getByRole("button", { name: studio.undo }));
  expect(sections()).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: studio.undo }));
  expect(sections()).toEqual([
    expect.stringMatching(/^Edytuj sekcję 1: Baner powitalny/),
  ]);
});

test("„Zmień zdjęcie” on the canvas opens the inspector at the section's photo", async () => {
  const photo = "019ff20d-a000-7000-8000-0000000000d1";
  listMediaAssets.mockResolvedValue({
    items: [
      {
        id: photo,
        original_filename: "pracownia.jpg",
        declared_mime: "image/jpeg",
        expected_size: 10,
        actual_size: 10,
        state: "ready",
        ai_origin: "",
        upload_expires_at: "2026-09-24T12:00:00Z",
        created_at: "2026-09-24T12:00:00Z",
      },
    ],
    next_cursor: null,
  });
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      {
        ...draft.blocks[0],
        schema_version: heroVersion,
        data: {
          title: "Oferta",
          image: { asset_id: photo, alt: "Pracownia" },
          layout: "split",
        },
      },
    ],
    media_asset_ids: [photo],
  });
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(
    await screen.findByRole("button", {
      name: polishMessages.Sites.studio.changeImageNamed.replace(
        "{alt}",
        "Pracownia",
      ),
    }),
  );
  const select = screen.getByLabelText(polishMessages.Sites.imageAsset);
  await waitFor(() => expect(select).toHaveFocus());
  expect(select).toHaveValue(photo);
});

test("Ctrl+Z and Ctrl+Y outside a text field are the page's undo and redo", async () => {
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  fireEvent.click(screen.getByRole("button", { name: "Powiel sekcję" }));
  const count = () =>
    screen.getAllByRole("button", { name: /Edytuj sekcję/ }).length;
  expect(count()).toBe(2);
  const canvas = screen.getByTestId("live-canvas");
  fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
  expect(count()).toBe(1);
  fireEvent.keyDown(canvas, { key: "y", ctrlKey: true });
  expect(count()).toBe(2);
  fireEvent.keyDown(canvas, { key: "Z", ctrlKey: true, shiftKey: true });
  expect(count()).toBe(2);
  // In a text field Ctrl+Z is the field's own.
  fireEvent.keyDown(screen.getByLabelText("Nagłówek"), {
    key: "z",
    ctrlKey: true,
  });
  expect(count()).toBe(2);
});

test.each(["pl", "en"] as const)(
  "studio rail inserts after the selection and shares undo (%s)",
  async (locale) => {
    renderEditor(
      locale,
      locale === "pl" ? polishMessages : englishMessages,
      vi.fn().mockResolvedValue(undefined),
      true,
    );
    await screen.findByLabelText(locale === "pl" ? "Nagłówek" : "Heading");
    const toggle = screen.getByRole("button", {
      name: locale === "pl" ? "Biblioteka sekcji" : "Section library",
    });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(
      screen.getByLabelText(locale === "pl" ? "Branża" : "Industry"),
      { target: { value: "medicine" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name:
          locale === "pl"
            ? "Dodaj: Ścieżka konsultacji"
            : "Add: Consultation pathway",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("live-canvas").querySelectorAll("[data-block-type]"),
      ).toHaveLength(2),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "pl" ? "Cofnij" : "Undo",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("live-canvas").querySelectorAll("[data-block-type]"),
      ).toHaveLength(1),
    );
    // The library, the outline and the inspector's hidden tabs share the
    // studio without duplicate field IDs.
    const ids = [...document.querySelectorAll("[id]")].map(
      (element) => element.id,
    );
    expect(new Set(ids).size).toBe(ids.length);
  },
);

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "studio navigation switches tools without losing the edited section (%s)",
  async (locale, messages) => {
    renderEditor(locale, messages, vi.fn().mockResolvedValue(undefined), true, {
      appearanceControls: <div>Appearance controls fixture</div>,
    });
    const heading = await screen.findByLabelText(
      locale === "pl" ? "Nagłówek" : "Heading",
    );
    fireEvent.change(heading, { target: { value: "Unsaved studio title" } });
    const rail = screen.getByRole("complementary", {
      name: messages.Sites.studio.pageNavigation,
    });
    const tools = within(rail).getByRole("group", {
      name: messages.Sites.studio.tools,
    });
    const outline = within(tools).getByRole("button", {
      name: messages.Sites.studio.sections,
    });
    const library = within(tools).getByRole("button", {
      name: messages.Sites.sectionLibrary.open,
    });
    const templates = within(tools).getByRole("button", {
      name: messages.Sites.studio.pageTemplates,
    });
    const design = within(tools).getByRole("button", {
      name: messages.Sites.studio.design,
    });
    expect(outline).toHaveAttribute("aria-pressed", "true");
    expect(
      within(rail).getByRole("button", { name: /Unsaved studio title/ }),
    ).toHaveAttribute("aria-current", "true");
    fireEvent.click(library);
    expect(library).toHaveAttribute("aria-pressed", "true");
    expect(outline).toHaveAttribute("aria-pressed", "false");
    expect(
      within(rail).getByRole("searchbox", {
        name: messages.Sites.sectionLibrary.search,
      }),
    ).toBeDefined();
    fireEvent.click(templates);
    expect(templates).toHaveAttribute("aria-pressed", "true");
    expect(within(rail).queryByRole("searchbox")).toBeNull();
    expect(
      within(rail).getAllByRole("img", {
        name: locale === "pl" ? /^Miniatura szablonu / : /^Thumbnail of the /,
      }),
    ).toHaveLength(offeredTemplates.length);
    fireEvent.click(design);
    expect(design).toHaveAttribute("aria-pressed", "true");
    expect(within(rail).getByText("Appearance controls fixture")).toBeDefined();
    expect(within(rail).queryByRole("img")).toBeNull();
    fireEvent.click(outline);
    expect(outline).toHaveAttribute("aria-pressed", "true");
    expect(
      within(rail).getByRole("button", { name: /Unsaved studio title/ }),
    ).toHaveAttribute("aria-current", "true");
    expect(heading).toHaveValue("Unsaved studio title");
    expect(screen.getByTestId("live-canvas")).toHaveTextContent(
      "Unsaved studio title",
    );
    expect(
      screen.getByRole("button", { name: messages.Sites.studio.undo }),
    ).not.toBeDisabled();
    expect(importPageTemplate).not.toHaveBeenCalled();
    expect(savePageDraft).not.toHaveBeenCalled();
  },
);

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "a template for a page with content shows the swap, cancel keeps the edits, confirm keeps the content (%s)",
  async (locale, messages) => {
    const onChanged = vi.fn().mockResolvedValue(undefined);
    const onExitStateChange = vi.fn();
    renderEditor(locale, messages, onChanged, true, { onExitStateChange });
    const heading = await screen.findByLabelText(
      locale === "pl" ? "Nagłówek" : "Heading",
    );
    fireEvent.change(heading, { target: { value: "Keep this local draft" } });
    await waitFor(() =>
      expect(onExitStateChange).toHaveBeenLastCalledWith({
        dirty: true,
        busy: false,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: messages.Sites.studio.pageTemplates }),
    );
    const useTemplate = templateUseButton(
      firstTemplate.labels[locale].name,
      locale,
    );
    fireEvent.click(useTemplate);
    const confirmation = screen.getByRole("dialog", {
      name: messages.Sites.templateSwap.title.replace(
        "{name}",
        firstTemplate.labels[locale].name,
      ),
    });
    expect(
      within(confirmation).getByText(messages.Sites.templateSwap.description),
    ).toBeDefined();
    // The page's hero goes into the template's hero; saying so names it.
    expect(confirmation).toHaveTextContent("Keep this local draft");
    expect(
      within(confirmation).getByText(messages.Sites.templateSwap.unsaved),
    ).toBeDefined();
    expect((await axe.run(confirmation)).violations).toHaveLength(0);
    expect(importPageTemplate).not.toHaveBeenCalled();
    expect(savePageDraft).not.toHaveBeenCalled();
    fireEvent.click(
      within(confirmation).getByRole("button", {
        name: messages.Common.cancel,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(heading).toHaveValue("Keep this local draft");
    expect(screen.getByTestId("live-canvas")).toHaveTextContent(
      "Keep this local draft",
    );
    expect(onExitStateChange).toHaveBeenLastCalledWith({
      dirty: true,
      busy: false,
    });
    expect(
      screen.getByRole("button", { name: messages.Sites.studio.undo }),
    ).not.toBeDisabled();
    expect(importPageTemplate).not.toHaveBeenCalled();
    fireEvent.click(useTemplate);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: messages.Sites.templateSwap.confirm,
      }),
    );
    await waitFor(() => expect(importPageTemplate).toHaveBeenCalledOnce());
    // The local edit became a version first, so nothing the swap leaves out
    // is lost; the import builds on that version.
    expect(savePageDraft).toHaveBeenCalledOnce();
    expect(savePageDraft.mock.calls[0]?.[1].blocks[0].data.title).toBe(
      "Keep this local draft",
    );
    expect(importPageTemplate.mock.calls[0]).toEqual([
      page.id,
      {
        expected_version: 2,
        template_id: firstTemplate.id,
        template_version: firstTemplate.version,
        locale,
        kept: [
          {
            slot: 0,
            block: expect.objectContaining({
              block_type: "core.hero",
              schema_version: heroVersion,
              data: expect.objectContaining({
                title: "Keep this local draft",
                layout: firstTemplate.blocks[0]!.data.layout,
              }),
            }),
          },
        ],
      },
      expect.any(String),
    ]);
    await waitFor(() =>
      expect(onExitStateChange).toHaveBeenLastCalledWith({
        dirty: false,
        busy: false,
      }),
    );
    expect(
      await screen.findByDisplayValue("Twoje imię i to, w czym pomagasz"),
    ).toBeDefined();
    expect(screen.getByTestId("live-canvas")).not.toHaveTextContent(
      "Keep this local draft",
    );
    expect(
      screen.getByRole("button", { name: messages.Sites.studio.undo }),
    ).toBeDisabled();
    expect(onChanged).toHaveBeenCalledOnce();
  },
);

test("the page's sections without a place are added or left out as chosen, or the template comes alone", async () => {
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      draft.blocks[0],
      {
        id: "019ff20d-a000-7000-8000-000000000028",
        position: 1,
        block_type: "core.separator",
        schema_version: 1,
        data: { layout: "wave" },
      },
    ],
  });
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const swap = polishMessages.Sites.templateSwap;
  const open = () => {
    fireEvent.click(
      screen.getByRole("button", {
        name: polishMessages.Sites.studio.pageTemplates,
      }),
    );
    fireEvent.click(templateUseButton(firstTemplate.labels.pl.name));
    return screen.getByRole("dialog");
  };

  let dialog = open();
  expect(
    within(dialog).getByRole("heading", {
      name: swap.unplaced.replace("{count}", "1"),
    }),
  ).toBeDefined();
  fireEvent.click(within(dialog).getByRole("radio", { name: swap.skip }));
  fireEvent.click(within(dialog).getByRole("button", { name: swap.confirm }));
  await waitFor(() => expect(importPageTemplate).toHaveBeenCalledOnce());
  // Nothing edited, nothing saved first; the separator stays in the history.
  expect(savePageDraft).not.toHaveBeenCalled();
  expect(importPageTemplate.mock.calls[0]?.[1]).not.toHaveProperty("appended");
  expect(importPageTemplate.mock.calls[0]?.[1].kept).toHaveLength(1);

  importPageTemplate.mockClear();
  getPageDraft.mockClear();
  dialog = open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: swap.templateOnly }),
  );
  await waitFor(() => expect(importPageTemplate).toHaveBeenCalledOnce());
  expect(importPageTemplate.mock.calls[0]?.[1]).not.toHaveProperty("kept");
});

test("metadata errors stay visible in the dialog and retry keeps the same request key", async () => {
  savePageTranslation.mockRejectedValueOnce(
    new Error("Unavailable metadata API"),
  );
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("en", englishMessages, onChanged);
  await screen.findByLabelText("Heading");
  await fromMore("Page settings", "More");
  const dialog = screen.getByRole("dialog", {
    name: englishMessages.Sites.metadata,
  });
  const title = within(dialog).getByLabelText("Page title");
  fireEvent.change(title, { target: { value: "Keep local metadata" } });
  const save = within(dialog).getByRole("button", { name: "Save metadata" });
  fireEvent.click(save);
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    englishMessages.Sites.problem,
  );
  expect(title).toHaveValue("Keep local metadata");
  expect(save).not.toBeDisabled();
  expect(onChanged).not.toHaveBeenCalled();
  fireEvent.click(save);
  await waitFor(() => expect(savePageTranslation).toHaveBeenCalledTimes(2));
  expect(savePageTranslation.mock.calls[0]).toEqual(
    savePageTranslation.mock.calls[1],
  );
  await waitFor(() => expect(within(dialog).queryByRole("alert")).toBeNull());
  expect(onChanged).toHaveBeenCalledOnce();
});

test("a pending metadata save disables fields, locale changes and repeat submission", async () => {
  let resolveSave!: (value: typeof translation) => void;
  savePageTranslation.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveSave = resolve;
      }),
  );
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");
  await fromMore("Page settings", "More");
  const dialog = screen.getByRole("dialog", {
    name: englishMessages.Sites.metadata,
  });
  const title = within(dialog).getByLabelText("Page title");
  const locale = within(dialog).getByRole("combobox", { name: "Language" });
  const save = within(dialog).getByRole("button", { name: "Save metadata" });
  fireEvent.change(title, { target: { value: "Pending metadata title" } });
  fireEvent.click(save);
  await waitFor(() => expect(savePageTranslation).toHaveBeenCalledOnce());
  expect(title).toBeDisabled();
  expect(within(dialog).getByLabelText("Meta description")).toBeDisabled();
  expect(locale).toBeDisabled();
  expect(save).toBeDisabled();
  // Native clicks respect disabled fieldsets, just like pointer/keyboard activation.
  locale.click();
  save.click();
  expect(screen.queryByRole("option", { name: "English" })).toBeNull();
  expect(savePageTranslation).toHaveBeenCalledOnce();
  await act(async () =>
    resolveSave({
      ...translation,
      title: "Pending metadata title",
      version: 2,
    }),
  );
  await waitFor(() => expect(save).not.toBeDisabled());
  expect(title).not.toBeDisabled();
  expect(locale).not.toBeDisabled();
  expect(title).toHaveValue("Pending metadata title");
});

test("invalid draft submission opens the mobile inspector and focuses the field", async () => {
  renderEditor(
    "en",
    englishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  const heading = await screen.findByLabelText("Heading");
  const workspace = screen.getByTestId("studio-workspace");
  expect(workspace).toHaveAttribute("data-mobile-panel", "canvas");
  fireEvent.change(heading, { target: { value: "" } });
  fireEvent.click(
    screen.getByRole("button", { name: englishMessages.Sites.studio.save }),
  );
  await waitFor(() =>
    expect(workspace).toHaveAttribute("data-mobile-panel", "inspector"),
  );
  await waitFor(() => expect(heading).toHaveFocus());
  expect(heading).toHaveAttribute("aria-invalid", "true");
  expect(savePageDraft).not.toHaveBeenCalled();
});

test("section decorations survive legacy migration, content/layout changes and undo/redo before saving", async () => {
  const decoration: SectionDecorationV1 = {
    schemaVersion: 1,
    background: "dots",
    frame: "accent",
    ornament: "rings",
    placement: "both",
    intensity: "soft",
    motion: "drift",
  };
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [{ ...draft.blocks[0], decoration }],
  });
  savePageDraft.mockImplementation(
    async (_id: string, input: DraftSaveInput) => ({
      ...draft,
      version: input.expected_version + 1,
      blocks: input.blocks.map((block, position) => ({
        ...block,
        id: draft.blocks[0].id,
        position,
      })),
    }),
  );
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const canvas = screen.getByTestId("live-canvas");
  expect(canvas.querySelector(".site-decoration")).toHaveClass(
    "site-decoration--bg-dots",
    "site-decoration--frame-accent",
    "site-decoration--motion-none",
    "site-decoration--preview",
  );

  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Zachowana dekoracja" },
  });
  fireEvent.change(screen.getByLabelText("Układ sekcji"), {
    target: { value: "split" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getByLabelText("Układ sekcji")).toHaveValue("classic");
  expect(screen.getByLabelText("Nagłówek")).toHaveValue("Zachowana dekoracja");
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(screen.getByLabelText("Nagłówek")).toHaveValue("Stary nagłówek");
  expect(canvas.querySelector(".site-decoration")).toHaveClass(
    "site-decoration--bg-dots",
  );
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  expect(screen.getByLabelText("Układ sekcji")).toHaveValue("split");
  fireEvent.click(screen.getByRole("button", { name: "Zapisz stronę" }));

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0][1].blocks).toEqual([
    {
      block_type: "core.hero",
      schema_version: heroVersion,
      data: {
        title: "Zachowana dekoracja",
        text: "Opis hero",
        layout: "split",
      },
      decoration,
    },
  ]);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Cofnij" })).toBeDisabled(),
  );
  expect(canvas.querySelector(".site-decoration")).toHaveClass(
    "site-decoration--bg-dots",
    "site-decoration--motion-none",
  );
  expect(draft.blocks[0].data).toEqual({
    heading: "Stary nagłówek",
    body: "Opis hero",
  });
});

test("section decoration preset persists, preview stays static and reset clears RHF state through undo/redo and save", async () => {
  const preset = sectionDecorationPresets.find(
    (item) => item.id === "floating_rings",
  )!;
  expect(preset.decoration.motion).not.toBe("none");
  let savedResponse: unknown = draft;
  savePageDraft.mockImplementation(
    async (_id: string, input: DraftSaveInput) => {
      savedResponse = {
        ...draft,
        version: input.expected_version + 1,
        blocks: input.blocks.map((block, position) => ({
          ...block,
          id: draft.blocks[0].id,
          position,
        })),
      };
      return savedResponse;
    },
  );
  getPageDraftPreview.mockImplementation(async () => savedResponse);
  renderEditor(
    "en",
    englishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Heading");
  const canvas = screen.getByTestId("live-canvas");
  expect(canvas.querySelector(".site-decoration")).toBeNull();
  // Decorations are under the inspector's "Style".
  fireEvent.click(screen.getByRole("tab", { name: "Style" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Ready-made style" }), {
    target: { value: preset.id },
  });
  expect(canvas.querySelector(".site-decoration")).toHaveClass(
    "site-decoration--preview",
    "site-decoration--motion-none",
  );
  expect(
    within(canvas).queryByRole("checkbox", {
      name: "Pause decorative animation",
    }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save page" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0][1].blocks[0].decoration).toEqual(
    preset.decoration,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled(),
  );

  fireEvent.click(screen.getByRole("button", { name: "Protected preview" }));
  const protectedPreview = await screen.findByTestId("draft-preview");
  expect(protectedPreview.querySelector(".site-decoration")).toHaveClass(
    "site-decoration--preview",
    "site-decoration--motion-none",
  );
  expect(
    within(protectedPreview).queryByRole("checkbox", {
      name: "Pause decorative animation",
    }),
  ).toBeNull();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByTestId("draft-preview")).toBeNull());

  // The inspector stayed on "Style" through the save and the preview.
  expect(screen.getByRole("tab", { name: "Style" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.getByRole("combobox", { name: "Ready-made style" }),
  ).toHaveValue(preset.id);
  fireEvent.click(
    screen.getByRole("button", {
      name: englishMessages.Sites.decorations.reset,
    }),
  );
  expect(canvas.querySelector(".site-decoration")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(canvas.querySelector(".site-decoration")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Redo" }));
  expect(canvas.querySelector(".site-decoration")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save page" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledTimes(2));
  expect(savePageDraft.mock.calls[1][1].expected_version).toBe(2);
  expect(savePageDraft.mock.calls[1][1].blocks[0]).not.toHaveProperty(
    "decoration",
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled(),
  );
  expect(canvas.querySelector(".site-decoration")).toBeNull();
});

test("separator editor restores stored dimensions and saves the selected layout, size, width and tone", async () => {
  getPageDraft.mockResolvedValue({
    ...draft,
    blocks: [
      {
        ...draft.blocks[0],
        block_type: "core.separator",
        schema_version: 1,
        data: { layout: "line", size: "small", width: "short", tone: "accent" },
      },
    ],
  });
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  expect(await screen.findByRole("combobox", { name: "Height" })).toHaveValue(
    "small",
  );
  expect(screen.getByRole("combobox", { name: "Width" })).toHaveValue("short");
  expect(screen.getByRole("combobox", { name: "Color" })).toHaveValue("accent");
  fireEvent.change(screen.getByRole("combobox", { name: "Height" }), {
    target: { value: "large" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Width" }), {
    target: { value: "full" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Color" }), {
    target: { value: "muted" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Section layout" }), {
    target: { value: "wave" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save page" }));
  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0][1].blocks).toEqual([
    {
      block_type: "core.separator",
      schema_version: 1,
      data: { layout: "wave", size: "large", width: "full", tone: "muted" },
    },
  ]);
});

function MediaFieldsHarness({
  assets,
  type,
  imageGeneration = null,
}: {
  assets: ComponentProps<typeof BlockFields>["assets"];
  type: string;
  imageGeneration?: typeof offer | null;
}) {
  // FieldValues: the block form's own Path types are too deep for a harness.
  const form = useForm<FieldValues>({
    defaultValues: { blocks: [emptyBlock(type)] },
  });
  return (
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <FormProvider {...form}>
        <PageEditorContext
          value={{ undo: vi.fn(), redo: vi.fn(), look: "", imageGeneration }}
        >
          <BlockFields
            assets={assets}
            form={form}
            index={0}
            isFirst
            isLast
            moveDown={vi.fn()}
            moveUp={vi.fn()}
            onRemove={vi.fn()}
            type={type}
          />
        </PageEditorContext>
      </FormProvider>
    </NextIntlClientProvider>
  );
}

const generateLabel = polishMessages.ImageGeneration.open;

test.each([
  ["core.hero", 1],
  // The section photo (4:3) yes, the author's portrait never (ADR-059 pkt 8).
  ["core.rich_text", 1],
  ["core.quote", 0],
])("%s offers AI generation on %i image field(s)", (type, count) => {
  render(
    <MediaFieldsHarness assets={[]} imageGeneration={offer} type={type} />,
  );
  expect(screen.queryAllByRole("button", { name: generateLabel })).toHaveLength(
    count,
  );
});

test("„Użyj” leaves the generated image selected in the field, also after leaving it", async () => {
  const generatedId = "019ff20d-a000-7000-8000-0000000000b1";
  requestImageGeneration.mockResolvedValue({
    id: "019ff20d-a000-7000-8000-0000000000b0",
    state: "succeeded",
    aspect: "16:9",
    width: 1536,
    height: 864,
    media_asset_id: generatedId,
    error_code: "",
    created_at: "2026-09-24T12:00:00Z",
    finished_at: "2026-09-24T12:01:00Z",
  });
  const messages = polishMessages.ImageGeneration;
  render(
    <MediaFieldsHarness assets={[]} imageGeneration={offer} type="core.hero" />,
  );
  fireEvent.click(screen.getByRole("button", { name: generateLabel }));
  fireEvent.change(screen.getByLabelText(messages.prompt), {
    target: { value: "Jasna pracownia" },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: messages.generate.replace("{cost}", "2"),
    }),
  );
  fireEvent.click(await screen.findByRole("button", { name: messages.use }));

  const select = screen.getByLabelText(
    polishMessages.Sites.imageAsset,
  ) as HTMLSelectElement;
  await waitFor(() => expect(select.value).toBe(generatedId));
  // The media list does not know the new asset yet; blurring must not lose it.
  fireEvent.blur(select);
  expect(select.value).toBe(generatedId);
  expect(select.selectedOptions[0]?.textContent).toBe(
    polishMessages.Sites.richText.currentImage,
  );
});

test.each([true, false])(
  "the draft preview badges AI images only while the badge is visible (%s)",
  async (badgeVisible) => {
    const aiId = "019ff20d-a000-7000-8000-0000000000c1";
    getImageGenerationOffer.mockResolvedValue({
      ...offer,
      badge_visible: badgeVisible,
    });
    listMediaAssets.mockResolvedValue({
      items: [
        {
          id: aiId,
          original_filename: "pracownia.jpg",
          declared_mime: "image/jpeg",
          expected_size: 10,
          actual_size: 10,
          state: "ready",
          ai_origin: "generated",
          upload_expires_at: "2026-09-24T12:00:00Z",
          created_at: "2026-09-24T12:00:00Z",
        },
      ],
      next_cursor: null,
    });
    getPageDraftPreview.mockResolvedValue({
      ...draft,
      blocks: [
        {
          ...draft.blocks[0],
          schema_version: heroVersion,
          data: {
            title: "Oferta",
            image: { asset_id: aiId, alt: "Pracownia" },
          },
        },
      ],
      media_asset_ids: [aiId],
    });
    renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
    await screen.findByLabelText("Nagłówek");
    fireEvent.click(
      screen.getAllByRole("button", { name: polishMessages.Sites.preview })[0]!,
    );
    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(Boolean(dialog.querySelector(".site-ai-badge"))).toBe(
        badgeVisible,
      ),
    );
  },
);

test("no AI button when the offer is unavailable or refused", () => {
  render(
    <MediaFieldsHarness
      assets={[]}
      imageGeneration={{ ...offer, available: false }}
      type="core.hero"
    />,
  );
  expect(screen.queryByRole("button", { name: generateLabel })).toBeNull();
  cleanup();
  render(<MediaFieldsHarness assets={[]} type="core.hero" />);
  expect(screen.queryByRole("button", { name: generateLabel })).toBeNull();
});

test("a figure in the text (3:2) offers AI generation", async () => {
  function FigureHarness() {
    const form = useForm<FieldValues>({
      defaultValues: {
        content: [
          {
            type: "figure",
            image: {
              asset_id: "00000000-0000-4000-8000-000000000001",
              alt: "",
            },
          },
        ],
      },
    });
    return (
      <NextIntlClientProvider locale="pl" messages={polishMessages}>
        <FormProvider {...form}>
          <PageEditorContext
            value={{
              undo: vi.fn(),
              redo: vi.fn(),
              look: "",
              imageGeneration: offer,
            }}
          >
            <RichTextEditor label="Treść" name="content" />
          </PageEditorContext>
        </FormProvider>
      </NextIntlClientProvider>
    );
  }
  render(<FigureHarness />);
  expect(
    await screen.findByRole("button", { name: generateLabel }),
  ).not.toBeNull();
});

test("the editor reads the offer once and shows the button only when it is available", async () => {
  getImageGenerationOffer.mockResolvedValue(offer);
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  expect(
    await screen.findByRole("button", { name: generateLabel }),
  ).not.toBeNull();
  expect(getImageGenerationOffer).toHaveBeenCalledOnce();
  cleanup();

  getImageGenerationOffer.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Forbidden",
      status: 403,
      code: "entitlement_required",
      detail: "Plan organizacji nie pozwala na tę operację.",
      correlation_id: null,
    }),
  );
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Nagłówek");
  expect(screen.queryByRole("button", { name: generateLabel })).toBeNull();
});

test("portret przy cytacie nie oferuje obrazów AI, hero oznacza je dopiskiem", () => {
  const base = {
    declared_mime: "image/jpeg",
    expected_size: 10,
    actual_size: 10,
    state: "ready",
    upload_expires_at: "2026-09-24T12:00:00Z",
    created_at: "2026-09-24T12:00:00Z",
  };
  const assets = [
    {
      ...base,
      id: "019ff20d-a000-7000-8000-000000000050",
      original_filename: "zespol.jpg",
      ai_origin: "none",
    },
    {
      ...base,
      id: "019ff20d-a000-7000-8000-000000000051",
      original_filename: "pracownia.jpg",
      ai_origin: "generated",
    },
  ];
  const options = (select: HTMLElement) =>
    within(select)
      .getAllByRole("option")
      .map((option) => option.textContent);

  render(<MediaFieldsHarness assets={assets} type="core.quote" />);
  expect(
    options(screen.getByLabelText(polishMessages.Sites.imageAsset)),
  ).toEqual([polishMessages.Sites.noImage, "zespol.jpg"]);
  cleanup();

  render(<MediaFieldsHarness assets={assets} type="core.hero" />);
  expect(
    options(screen.getByLabelText(polishMessages.Sites.imageAsset)),
  ).toEqual([polishMessages.Sites.noImage, "zespol.jpg", "pracownia.jpg · AI"]);
  expect(polishMessages.Sites.aiSuffix).toBe(" · AI");
  expect(englishMessages.Sites.aiSuffix).toBe(" · AI");
});

const templateAuthor = {
  id: "019ff20d-a000-7000-8000-0000000000f9",
  email: "ania@example.test",
};

function ownTemplate(kind: "section" | "page", name: string, number = 1) {
  return {
    id:
      kind === "section"
        ? "019ff20d-a000-7000-8000-0000000000f1"
        : "019ff20d-a000-7000-8000-0000000000f2",
    kind,
    name,
    description: "",
    created_by: templateAuthor,
    created_at: "2026-09-28T12:00:00Z",
    updated_at: "2026-09-28T12:00:00Z",
    version: {
      number,
      blocks: [
        {
          block_type: "core.hero",
          schema_version: heroVersion,
          data: { title: "Z szablonu firmy", text: "Opis" },
        },
      ],
      page_presentation: null,
      media_asset_ids: [],
      created_by: templateAuthor,
      created_at: "2026-09-28T12:00:00Z",
    },
  };
}

test("zapisuje zaznaczoną sekcję jako szablon firmy, nie zapisując strony", async () => {
  createSiteTemplate.mockResolvedValue(ownTemplate("section", "Oferta"));
  renderEditor(
    "pl",
    polishMessages,
    vi.fn().mockResolvedValue(undefined),
    true,
  );
  await screen.findByLabelText("Nagłówek");
  const own = polishMessages.Sites.ownTemplates;
  fireEvent.click(screen.getByRole("button", { name: own.saveSection }));
  const dialog = await screen.findByRole("dialog", {
    name: own.saveSectionTitle,
  });
  fireEvent.change(within(dialog).getByLabelText(own.name), {
    target: { value: "Oferta" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: own.save }));

  await waitFor(() => expect(createSiteTemplate).toHaveBeenCalledOnce());
  expect(createSiteTemplate.mock.calls[0]).toEqual([
    {
      kind: "section",
      name: "Oferta",
      description: "",
      blocks: [
        {
          block_type: "core.hero",
          schema_version: heroVersion,
          data: {
            layout: "classic",
            title: "Stary nagłówek",
            text: "Opis hero",
          },
        },
      ],
      page_presentation: null,
      media_asset_ids: [],
      source_page_id: page.id,
    },
    expect.any(String),
  ]);
  expect(
    await within(dialog).findByText(
      "Zapisano szablon „Oferta”. Znajdziesz go w bibliotece w grupie „Szablony firmy”.",
    ),
  ).toHaveAttribute("role", "status");
  // The template dialog's form is not the page's: nothing saved there.
  expect(savePageDraft).not.toHaveBeenCalled();
});

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "a company page template takes the page's content in its places after confirmation (%s)",
  async (locale, messages) => {
    listSiteTemplates.mockImplementation(async (kind?: string) => ({
      items: kind === "page" ? [ownTemplate("page", "Strona usługi", 2)] : [],
      limit: null,
    }));
    importOwnPageTemplate.mockResolvedValue({
      ...draft,
      version: 2,
      draft_id: "019ff20d-a000-7000-8000-0000000000f3",
      blocks: [
        {
          ...draft.blocks[0],
          schema_version: heroVersion,
          data: { title: "Z szablonu firmy", text: "Opis" },
        },
      ],
    });
    renderEditor(locale, messages, vi.fn().mockResolvedValue(undefined), true);
    await screen.findByLabelText(locale === "pl" ? "Nagłówek" : "Heading");
    fireEvent.click(
      screen.getByRole("button", { name: messages.Sites.studio.pageTemplates }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name:
          locale === "pl"
            ? "Użyj szablonu firmy „Strona usługi”"
            : "Use the company template “Strona usługi”",
      }),
    );
    const confirmation = screen.getByRole("dialog", {
      name: messages.Sites.templateSwap.title.replace(
        "{name}",
        "Strona usługi",
      ),
    });
    expect(importOwnPageTemplate).not.toHaveBeenCalled();
    fireEvent.click(
      within(confirmation).getByRole("button", {
        name: messages.Sites.templateSwap.confirm,
      }),
    );
    await waitFor(() => expect(importOwnPageTemplate).toHaveBeenCalledOnce());
    expect(importOwnPageTemplate.mock.calls[0]).toEqual([
      page.id,
      {
        expected_version: 1,
        template_id: "019ff20d-a000-7000-8000-0000000000f2",
        template_version: 2,
        kept: [
          {
            slot: 0,
            block: expect.objectContaining({
              block_type: "core.hero",
              data: expect.objectContaining({ title: "Stary nagłówek" }),
            }),
          },
        ],
      },
      expect.any(String),
    ]);
    expect(await screen.findByDisplayValue("Z szablonu firmy")).toBeDefined();
    expect(savePageDraft).not.toHaveBeenCalled();
  },
);
