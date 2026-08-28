import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageEditor } from "./page-editor";
import { PublicationHistory } from "./publication-history";

const {
  completeMediaUpload,
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
        schema_version: 3,
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
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[0]).toBe(page.id);
  expect(savePageDraft.mock.calls[0]?.[1]).toMatchObject({
    expected_version: 1,
    blocks: [
      {
        block_type: "core.hero",
        // Saved at the current contract version: the editor migrates a v1
        // draft on load, so what leaves the panel is always the latest.
        schema_version: 3,
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
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  expect(
    await screen.findByText("Tekst jest za długi dla tego bloku."),
  ).not.toBeNull();
  expect(savePageDraft).not.toHaveBeenCalled();

  fireEvent.change(text, { target: { value: "x".repeat(600) } });
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );
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
  // Two "Dodaj" buttons exist — this one adds a block, the other adds media.
  fireEvent.click(screen.getAllByRole("button", { name: "Dodaj" })[0]);

  fireEvent.click(await screen.findByRole("button", { name: "Dodaj pozycję" }));
  fireEvent.change(await screen.findByLabelText("Pytanie"), {
    target: { value: "Ile trwa wizyta?" },
  });
  fireEvent.change(screen.getByLabelText("Odpowiedź"), {
    target: { value: "Około godziny." },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  await waitFor(() => expect(savePageDraft).toHaveBeenCalledOnce());
  expect(savePageDraft.mock.calls[0]?.[1].blocks[1]).toEqual({
    block_type: "core.faq",
    schema_version: 1,
    // `title` was left blank and is optional, so it is absent rather than "".
    data: {
      items: [{ question: "Ile trwa wizyta?", answer: "Około godziny." }],
    },
  });
});

test("importuje szablon do wersjonowanego draftu przez API", async () => {
  getPageDraft.mockResolvedValue({ ...draft, blocks: [] });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderEditor("pl", polishMessages, onChanged);

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
    template_version: 1,
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
    renderEditor(locale, messages, vi.fn().mockResolvedValue(undefined));

    const thumbnailElement = await screen.findByRole("img", {
      name: thumbnail,
    });
    const templateGrid = thumbnailElement.closest("ul");
    expect(templateGrid?.className).toContain("grid");
    expect(templateGrid?.className).toContain("sm:grid-cols-3");

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
  // Two "Dodaj" buttons exist — this one adds a block, the other adds media.
  fireEvent.click(screen.getAllByRole("button", { name: "Dodaj" })[0]);
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  expect(await screen.findByRole("alert")).not.toBeNull();
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
  fireEvent.click(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  );

  expect(await screen.findByText(/Ktoś zapisał nowszy draft/)).not.toBeNull();
  expect((screen.getByLabelText("Nagłówek") as HTMLInputElement).value).toBe(
    "Moja lokalna wersja",
  );
  expect(
    screen.getByRole("button", { name: "Zapisz nową wersję draftu" }),
  ).toBeDisabled();
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
});

test("zapisuje metadane EN z jawnym fallbackiem i optimistic lockiem", async () => {
  renderEditor("en", englishMessages, vi.fn().mockResolvedValue(undefined));
  await screen.findByLabelText("Heading");

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
