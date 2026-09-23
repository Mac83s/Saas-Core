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
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type DraftSaveInput } from "@saas-core/api-client";
import {
  sectionDecorationPresets,
  type SectionDecorationV1,
} from "@saas-core/site-blocks";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageEditor } from "./page-editor";
import { PublicationHistory } from "./publication-history";

const {
  completeMediaUpload,
  materializeTemplatePhoto,
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
  initiateMediaUpload,
  listMediaAssets,
  listPageTranslations,
  savePageDraft,
  savePageTranslation,
} = vi.hoisted(() => ({
  completeMediaUpload: vi.fn(),
  materializeTemplatePhoto: vi.fn(),
  getPageDraft: vi.fn(),
  getPageDraftPreview: vi.fn(),
  importPageTemplate: vi.fn(),
  initiateMediaUpload: vi.fn(),
  listMediaAssets: vi.fn(),
  listPageTranslations: vi.fn(),
  savePageDraft: vi.fn(),
  savePageTranslation: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  completeMediaUpload,
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
  savePageDraft,
  savePageTranslation,
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
        schema_version: 5,
        data: { title: "Nowy nagłówek", text: "Opis hero" },
      },
    ],
  });
  expect(onChanged).toHaveBeenCalledOnce();
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
    await screen.findByText("Tekst jest za długi dla tego bloku."),
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
  const picker = await screen.findByRole("combobox", { name: "Typ bloku" });
  picker.focus();
  fireEvent.change(picker, { target: { value: "FAQ" } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "FAQ" }));
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

test("importuje szablon do wersjonowanego draftu przez API", async () => {
  getPageDraft.mockResolvedValue({ ...draft, blocks: [] });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged, true);

  // An empty page offers templates instead of a bare "no sections" message.
  fireEvent.click(
    await screen.findByRole("button", { name: "Użyj szablonu Wizytówka" }),
  );

  expect(await screen.findByDisplayValue(/Twoje imię/)).not.toBeNull();
  expect(importPageTemplate).toHaveBeenCalledOnce();
  expect(importPageTemplate.mock.calls[0]?.[0]).toBe(page.id);
  expect(importPageTemplate.mock.calls[0]?.[1]).toEqual({
    expected_version: 1,
    template_id: "core.profile",
    template_version: 2,
    locale: "pl",
  });
  expect(savePageDraft).not.toHaveBeenCalled();
  expect(onChanged).toHaveBeenCalledOnce();
});

test.each([
  {
    locale: "pl" as const,
    messages: polishMessages,
    thumbnail: "Miniatura szablonu Wizytówka",
    previewButton: "Zobacz podgląd",
    previewTitle: "Podgląd szablonu Wizytówka",
  },
  {
    locale: "en" as const,
    messages: englishMessages,
    thumbnail: "Thumbnail of the Profile template",
    previewButton: "Preview",
    previewTitle: "Preview of the Profile template",
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
    expect(within(templateGrid!).getAllByRole("img")).toHaveLength(11);

    const trigger = screen.getAllByRole("button", {
      name: previewButton,
    })[0];
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
);

test("nie wysyła sekcji FAQ bez ani jednego wpisu", async () => {
  renderEditor("pl", polishMessages, vi.fn().mockResolvedValue(undefined));

  const picker = await screen.findByRole("combobox", { name: "Typ bloku" });
  picker.focus();
  fireEvent.change(picker, { target: { value: "FAQ" } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "FAQ" }));
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

  expect(await screen.findByText(/Ktoś zapisał nowszy draft/)).not.toBeNull();
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Moja lokalna wersja",
  );
  expect(screen.getByRole("button", { name: "Zapisz stronę" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Wczytaj wersję serwera" }),
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

test("zapisuje metadane EN z jawnym fallbackiem i optimistic lockiem", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");

  fireEvent.click(screen.getByRole("button", { name: "Page settings" }));
  const localeSelect = screen.getByRole("combobox", { name: "Locale" });
  fireEvent.click(localeSelect);
  const englishOption = await screen.findByRole("option", { name: "English" });
  fireEvent.pointerDown(englishOption, { button: 0 });
  fireEvent.pointerUp(englishOption, { button: 0 });
  fireEvent.click(englishOption);
  await screen.findByRole("checkbox", {
    name: "Allow fallback for Meta description",
  });
  fireEvent.change(screen.getByLabelText("Page title"), {
    target: { value: "English home" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Allow fallback for Meta description",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save metadata" }));

  await waitFor(() => expect(savePageTranslation).toHaveBeenCalledOnce());
  expect(savePageTranslation.mock.calls[0]?.slice(0, 3)).toEqual([
    page.id,
    "en",
    expect.objectContaining({
      slug: "home",
      title: "English home",
      allow_description_fallback: true,
      expected_version: 0,
    }),
  ]);
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

  fireEvent.click(screen.getByRole("button", { name: "Ustawienia strony" }));
  fireEvent.change(screen.getByLabelText("Tytuł strony"), {
    target: { value: "Moja lokalna metadata" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz metadane" }));

  expect(
    await screen.findByText(/Ktoś zapisał nowsze metadane/),
  ).not.toBeNull();
  expect(
    (screen.getByLabelText("Tytuł strony") as HTMLInputElement).value,
  ).toBe("Moja lokalna metadata");
  expect(
    screen.getByRole("button", { name: "Zapisz metadane" }),
  ).toBeDisabled();
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

  fireEvent.click(
    screen.getByRole("button", { name: polishMessages.Sites.media }),
  );
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

test("historia pokazuje autora i przekazuje wybraną publikację do rollbacku", () => {
  const onRollback = vi.fn();
  const publication = {
    id: "019ff20d-a000-7000-8000-000000000025",
    site_id: page.site_id,
    sequence: 2,
    snapshot_schema_version: 1,
    snapshot_hash: "b".repeat(64),
    source_publication_id: "019ff20d-a000-7000-8000-000000000026",
    created_by: {
      id: "019ff20d-a000-7000-8000-000000000027",
      email: "owner@example.test",
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
    screen.getByRole("button", { name: "Przywróć jako nową publikację" }),
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

function renderEditor(
  locale: "pl" | "en",
  messages: typeof polishMessages | typeof englishMessages,
  onChanged: () => Promise<void>,
  visual = false,
  extraProps: Pick<
    ComponentProps<typeof PageEditor>,
    "appearanceControls" | "onExitStateChange"
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
    schema_version: 4,
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
    schema_version: 5,
    data: { title: "Stary nagłówek", text: "Opis hero", layout: "split" },
  });
});

test("biblioteka EN pokazuje opis, dostępny podgląd i angielską treść", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");
  fireEvent.click(screen.getByRole("button", { name: "Section library" }));
  // Editorial, quote and product families now share the first dozen cards.
  fireEvent.click(
    await screen.findByRole("button", { name: /^Show more layouts/ }),
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
  fireEvent.click(screen.getByRole("button", { name: "Dodaj sekcję poniżej" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj: Karty usług" }),
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
    // Contextual dialog can coexist with the rail without duplicate field IDs.
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "pl" ? "Dodaj sekcję poniżej" : "Add section below",
      }),
    );
    await screen.findByRole("dialog");
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
      within(rail).getAllByRole("button", {
        name: locale === "pl" ? /^Użyj szablonu / : /^Use /,
      }),
    ).toHaveLength(11);
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
  "replacing existing content requires confirmation and cancel preserves dirty edits (%s)",
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
    const useTemplate = screen.getByRole("button", {
      name:
        locale === "pl"
          ? "Użyj szablonu Wizytówka"
          : "Use the Profile template",
    });
    fireEvent.click(useTemplate);
    const confirmation = screen.getByRole("dialog", {
      name: messages.Sites.studio.replaceTitle,
    });
    expect(
      within(confirmation).getByText(messages.Sites.studio.replaceDescription),
    ).toBeDefined();
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
        name: messages.Sites.studio.replaceConfirm,
      }),
    );
    await waitFor(() => expect(importPageTemplate).toHaveBeenCalledOnce());
    expect(importPageTemplate.mock.calls[0]).toEqual([
      page.id,
      {
        expected_version: 1,
        template_id: "core.profile",
        template_version: 2,
        locale,
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
    expect(savePageDraft).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledOnce();
  },
);

test("metadata errors stay visible in the dialog and retry keeps the same request key", async () => {
  savePageTranslation.mockRejectedValueOnce(
    new Error("Unavailable metadata API"),
  );
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("en", englishMessages, onChanged);
  await screen.findByLabelText("Heading");
  fireEvent.click(screen.getByRole("button", { name: "Page settings" }));
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
  fireEvent.click(screen.getByRole("button", { name: "Page settings" }));
  const dialog = screen.getByRole("dialog", {
    name: englishMessages.Sites.metadata,
  });
  const title = within(dialog).getByLabelText("Page title");
  const locale = within(dialog).getByRole("combobox", { name: "Locale" });
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
      schema_version: 5,
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
  fireEvent.click(
    screen.getByText("Section decorations", { selector: "summary" }),
  );
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

  const summary = screen.getByText("Section decorations", {
    selector: "summary",
  });
  if (!(summary.closest("details") as HTMLDetailsElement).open)
    fireEvent.click(summary);
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
