import type { ReactNode } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type LocaleBody } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageLanguageEditor } from "./page-language-editor";

const api = vi.hoisted(() => ({
  getLocaleBody: vi.fn(),
  saveLocaleBody: vi.fn(),
  getLocaleBodyVersion: vi.fn(),
  listLocaleBodyVersions: vi.fn(),
  listPageTranslations: vi.fn(),
  previewRebaseLocaleBody: vi.fn(),
  rebaseLocaleBody: vi.fn(),
  restoreLocaleBodyVersion: vi.fn(),
  savePageTranslation: vi.fn(),
  acceptLocaleBody: vi.fn(),
  rejectLocaleBody: vi.fn(),
  previewPublishLocaleBody: vi.fn(),
  publishLocaleBody: vi.fn(),
  withdrawLocaleBody: vi.fn(),
  getTranslationOffer: vi.fn(),
  getTranslationJob: vi.fn(),
  quoteTranslation: vi.fn(),
  orderTranslation: vi.fn(),
  getCustomerCredits: vi.fn(),
  readSeoPreview: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const PAGE = {
  id: "019ff20d-a000-7000-8000-000000000001",
  site_id: "019ff20d-a000-7000-8000-000000000002",
  key: "oferta",
  name: "Oferta",
} as Parameters<typeof PageLanguageEditor>[0]["page"];

function unit(
  key: string,
  source: string,
  extra: Partial<LocaleBody["units"][number]> = {},
): LocaleBody["units"][number] {
  return {
    key,
    kind: "text",
    source_text: source,
    text: null,
    origin: "",
    translated: false,
    suggestion: null,
    data_class: "public",
    placeholder: false,
    max_length: null,
    required_text: false,
    marks: [],
    ...extra,
  } as LocaleBody["units"][number];
}

function body(extra: Partial<LocaleBody> = {}): LocaleBody {
  return {
    page_id: PAGE.id,
    locale: "de",
    source_version_id: "019ff20d-a000-7000-8000-0000000000aa",
    source_version: 3,
    outdated: false,
    body_version: 1,
    version: 1,
    version_id: "019ff20d-a000-7000-8000-0000000000bb",
    pending: null,
    withdrawn: false,
    live_version_id: null,
    untranslated: 1,
    block_types: ["core.hero", "core.contact_details"],
    units: [
      // Stored with the text first; the form shows the heading first.
      unit("0/text", "Projekt od 120 zł"),
      unit("0/title", "Oferta", {
        text: "Angebot",
        origin: "ai",
        translated: true,
      }),
      unit("1/name", "Studio Kowalski", { kind: "name", translated: true }),
      unit("1/note", "[Uzupełnij: godziny]", { placeholder: true }),
    ],
    ...extra,
  } as LocaleBody;
}

function show(locale: "pl" | "en" = "pl", leading?: ReactNode) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <PageLanguageEditor
        page={PAGE}
        locale="de"
        languageName="Deutsch"
        sourceName="Polski"
        leading={leading}
        languageSwitch={null}
        onSwitchToSource={vi.fn()}
        onChanged={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // No translation engine composed, unless a test says otherwise.
  api.getTranslationOffer.mockRejectedValue(new Error("not found"));
  // The search preview of the address dialog stays loading unless asked.
  api.readSeoPreview.mockReturnValue(new Promise(() => undefined));
});

test("only the words change: each fragment beside its source, structure in the source", async () => {
  api.getLocaleBody.mockResolvedValue(body());
  const view = show();

  expect(await screen.findByText("1. Baner powitalny")).not.toBeNull();
  // The section's own field order: the heading before the text.
  const labels = screen
    .getAllByText(/^(Nagłówek|Treść)$/)
    .map((item) => item.textContent);
  expect(labels).toEqual(["Nagłówek", "Treść"]);
  expect(screen.getByText("Projekt od 120 zł")).not.toBeNull();
  expect(screen.getByDisplayValue("Angebot")).not.toBeNull();
  expect(screen.getByText("Przetłumaczone (AI)")).not.toBeNull();
  // A name is the same everywhere; a slot waits for the source.
  expect(screen.getByText("Taki sam we wszystkich językach")).not.toBeNull();
  expect(
    screen.getByText("Najpierw uzupełnij w wersji źródłowej"),
  ).not.toBeNull();
  expect(
    screen.getByText("Układ, zdjęcia i linki zmieniasz w wersji źródłowej.", {
      exact: false,
    }),
  ).not.toBeNull();
  // Nothing here adds, moves or removes a section, an image or a link.
  for (const name of [
    /dodaj sekcję/i,
    /usuń/i,
    /przesuń/i,
    /media/i,
    /zdjęci/i,
  ]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
  expect(screen.getByText(/Brakuje 1 fragmentu/)).not.toBeNull();
  expect((await axe.run(view.container)).violations).toEqual([]);
});

test("one top bar, as the source's editor has: the way back, the page and its language, then saving", async () => {
  api.getLocaleBody.mockResolvedValue(body());
  show("pl", <button type="button">Wróć do podstron</button>);

  const save = await screen.findByRole("button", {
    name: "Zapisz tłumaczenie",
  });
  const bar = save.closest<HTMLElement>(".studio-topbar");
  expect(bar).not.toBeNull();
  const row = within(bar!);
  expect(row.getByRole("button", { name: "Wróć do podstron" })).toBeDefined();
  expect(row.getByText("Oferta")).toBeDefined();
  expect(await row.findByText("Deutsch · Wersja 1")).toBeDefined();
  expect(row.getByRole("button", { name: "Więcej" })).toBeDefined();
  expect(row.getByRole("button", { name: "Podgląd" })).toBeDefined();
  expect(
    row.getByRole("button", { name: "Przejdź do wersji: Polski" }),
  ).toBeDefined();
});

test("saving sends only what changed and the fragment reads as corrected", async () => {
  api.getLocaleBody.mockResolvedValue(body());
  api.saveLocaleBody.mockImplementation(async (_page, _locale, input) =>
    body({
      body_version: 2,
      version: 2,
      untranslated: 0,
      units: body().units.map((item) =>
        item.key === "0/text"
          ? {
              ...item,
              text: input.units["0/text"],
              origin: "human",
              translated: true,
            }
          : item,
      ),
    }),
  );
  show();

  const field = await screen.findByLabelText("Treść");
  fireEvent.change(field, { target: { value: "Entwurf ab 120 zł" } });
  expect(screen.getByText("Niezapisane")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Zapisz tłumaczenie" }));

  await waitFor(() => expect(api.saveLocaleBody).toHaveBeenCalledTimes(1));
  expect(api.saveLocaleBody.mock.calls[0]?.[2]).toEqual({
    source_version_id: body().source_version_id,
    expected_body_version: 1,
    units: { "0/text": "Entwurf ab 120 zł" },
  });
  expect(await screen.findByText("Poprawione")).not.toBeNull();
  expect(screen.getByText("Zapisano tłumaczenie: Deutsch.")).not.toBeNull();
});

test("after a conflict the new version loads and the unsaved words go back on top", async () => {
  api.getLocaleBody.mockResolvedValueOnce(body()).mockResolvedValueOnce(
    body({
      body_version: 5,
      units: body().units.map((item) =>
        item.key === "0/title" ? { ...item, text: "Unser Angebot" } : item,
      ),
    }),
  );
  api.saveLocaleBody.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "locale_body_version_conflict",
      detail: "",
      correlation_id: null,
    }),
  );
  show();

  const field = await screen.findByLabelText("Treść");
  fireEvent.change(field, { target: { value: "Entwurf ab 120 zł" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz tłumaczenie" }));

  expect(await screen.findByText(/Ktoś zmienił to tłumaczenie/)).not.toBeNull();
  // Somebody else's title stays; this person's words are still in the field.
  expect(screen.getByDisplayValue("Unser Angebot")).not.toBeNull();
  expect(screen.getByDisplayValue("Entwurf ab 120 zł")).not.toBeNull();
});

test("keeping a fragment unchanged makes the source text this language's", async () => {
  api.getLocaleBody.mockResolvedValue(body());
  show();

  await screen.findByLabelText("Treść");
  fireEvent.click(screen.getByRole("button", { name: "Zostaw bez zmian" }));
  expect(screen.getByDisplayValue("Projekt od 120 zł")).not.toBeNull();
  expect(screen.getByText("Niezapisane")).not.toBeNull();
});

test("a language without an address asks for one before any text", async () => {
  api.getLocaleBody.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Not found",
      status: 404,
      code: "translation_not_found",
      detail: "",
      correlation_id: null,
    }),
  );
  api.listPageTranslations.mockResolvedValue({ page_id: PAGE.id, items: [] });
  const view = show("en");

  expect(
    await screen.findByText("This version has no address yet"),
  ).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Add an address and a title" }),
  );
  expect(await screen.findByRole("dialog")).not.toBeNull();
  expect((await axe.run(view.container)).violations).toEqual([]);
});

test("a page with no version yet starts from an empty state", async () => {
  api.getLocaleBody.mockResolvedValue(
    body({
      version: null,
      version_id: null,
      units: body().units.map((item) => ({ ...item, text: null, origin: "" })),
    }),
  );
  show();

  expect(
    await screen.findByText("Ta strona nie ma jeszcze wersji: Deutsch"),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Przetłumacz ręcznie" }));
  expect(await screen.findByLabelText("Treść")).not.toBeNull();
});

const DECISION = {
  page_id: PAGE.id,
  locale: "de",
  published: true,
  publication_id: "019ff20d-a000-7000-8000-0000000000cc",
  skipped: null,
};

test("a waiting translation is accepted and published from the banner", async () => {
  api.getLocaleBody.mockResolvedValue(
    body({
      untranslated: 0,
      pending: {
        version_id: "019ff20d-a000-7000-8000-0000000000dd",
        number: 2,
        reason: "review_mode",
      },
    }),
  );
  api.acceptLocaleBody.mockResolvedValue(DECISION);
  show();

  expect(
    await screen.findByText(
      "Tłumaczenie czeka na Twoją decyzję: tłumaczenia w tej firmie czekają na akceptację.",
    ),
  ).not.toBeNull();
  expect(screen.getByRole("button", { name: "Odrzuć" })).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Zaakceptuj i opublikuj" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(
    "Wersja Deutsch tej strony trafi na stronę",
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Zaakceptuj i opublikuj" }).at(-1)!,
  );

  await waitFor(() =>
    expect(api.acceptLocaleBody).toHaveBeenCalledWith(
      PAGE.id,
      "de",
      1,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Tłumaczenie zaakceptowane i opublikowane."),
  ).not.toBeNull();
});

test("a complete version that can go out is published after one confirmation", async () => {
  api.getLocaleBody.mockResolvedValue(body({ untranslated: 0 }));
  // As the server answers a preview: nothing went out, and nothing stops it.
  api.previewPublishLocaleBody.mockResolvedValue({
    ...DECISION,
    published: false,
    publication_id: null,
    skipped: null,
  });
  api.publishLocaleBody.mockResolvedValue(DECISION);
  show();

  fireEvent.click(
    await screen.findByRole("button", { name: "Opublikuj tę wersję" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(
    "Opublikować wersję Deutsch tej strony?",
  );
  expect(api.publishLocaleBody).not.toHaveBeenCalled();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Opublikuj tę wersję" }),
  );

  await waitFor(() =>
    expect(api.publishLocaleBody).toHaveBeenCalledWith(
      PAGE.id,
      "de",
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Wersja Deutsch jest na stronie."),
  ).not.toBeNull();
});

test("a complete version says it is not on the site and why it cannot go yet", async () => {
  api.getLocaleBody.mockResolvedValue(body({ untranslated: 0 }));
  api.previewPublishLocaleBody.mockResolvedValue({
    ...DECISION,
    published: false,
    publication_id: null,
    skipped: "locale_home_missing",
  });
  show();

  expect(
    await screen.findByText(
      "Ta wersja jest gotowa, ale nie ma jej jeszcze na stronie.",
    ),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Opublikuj tę wersję" }));

  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(
    "Tej wersji nie można jeszcze opublikować",
  );
  expect(dialog.textContent).toContain(
    "Najpierw musi wyjść strona główna w tym języku.",
  );
  expect(api.publishLocaleBody).not.toHaveBeenCalled();
});

test("a decision the person may not take says who takes it", async () => {
  const live = body().version_id;
  api.getLocaleBody.mockResolvedValue(
    body({ untranslated: 0, live_version_id: live }),
  );
  api.withdrawLocaleBody.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Forbidden",
      status: 403,
      code: "permission_denied",
      detail: "",
      correlation_id: null,
    }),
  );
  show();

  expect(await screen.findByText("Ta wersja jest na stronie.")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Więcej" }));
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Zdejmij ze strony" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Zdejmij ze strony" }),
  );
  expect(
    await screen.findByText("Tę decyzję podejmuje osoba z prawem publikacji."),
  ).not.toBeNull();
});

const EMPTY = () =>
  body({
    version: null,
    version_id: null,
    units: body().units.map((item) => ({ ...item, text: null, origin: "" })),
  });

test("an engine that takes no orders leaves the manual way whole and says why", async () => {
  api.getLocaleBody.mockResolvedValue(EMPTY());
  api.getTranslationOffer.mockResolvedValue({
    available: false,
    reasons: ["model_not_selected"],
  });
  show();

  expect(
    await screen.findByText(
      "Automatyczne tłumaczenie nie jest teraz dostępne: platforma nie wybrała jeszcze modelu tłumaczeń. Możesz przetłumaczyć ręcznie.",
    ),
  ).not.toBeNull();
  // No button that leads nowhere.
  expect(screen.queryByRole("button", { name: "Przetłumacz (AI)" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Przetłumacz ręcznie" }));
  expect(await screen.findByLabelText("Treść")).not.toBeNull();
});

test("an order from the empty state is followed and the page reloads when it ends", async () => {
  api.getLocaleBody
    .mockResolvedValueOnce(EMPTY())
    .mockResolvedValue(body({ untranslated: 0 }));
  api.getTranslationOffer.mockResolvedValue({
    available: true,
    reasons: [],
    billing: { mode: "credits" },
  });
  api.getCustomerCredits.mockResolvedValue({ balance: { available: 5 } });
  api.quoteTranslation.mockResolvedValue({
    digest: "d".repeat(64),
    characters: 120,
    units: 1,
    credits: 1,
    lines: [
      {
        object_id: PAGE.id,
        locale: "de",
        proposals: 0,
        outcome: "draft",
        reason: null,
        excluded: null,
      },
    ],
  });
  api.orderTranslation.mockResolvedValue({ id: "job-1", state: "queued" });
  api.getTranslationJob.mockResolvedValue({ id: "job-1", state: "succeeded" });
  show();

  fireEvent.click(
    await screen.findByRole("button", { name: "Przetłumacz (AI)" }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Przetłumacz" }));

  await waitFor(() =>
    expect(api.orderTranslation).toHaveBeenCalledWith(
      [
        {
          source_key: "sites.page",
          object_id: PAGE.id,
          locale: "de",
          basis: "published",
        },
      ],
      expect.anything(),
      expect.any(String),
      "propose",
    ),
  );
  expect(
    await screen.findByText("Tłumaczenie gotowe — poniżej nowa wersja."),
  ).not.toBeNull();
  expect(api.getLocaleBody).toHaveBeenCalledTimes(2);
});

test("an order that ended is history: asking again quotes anew", async () => {
  // Fragments are still missing after the order, so the banner offers it again.
  api.getLocaleBody.mockResolvedValue(body());
  api.getTranslationOffer.mockResolvedValue({
    available: true,
    reasons: [],
    billing: { mode: "credits" },
  });
  api.getCustomerCredits.mockResolvedValue({ balance: { available: 5 } });
  api.quoteTranslation.mockResolvedValue({
    digest: "d".repeat(64),
    characters: 40,
    units: 1,
    credits: 1,
    lines: [
      {
        object_id: PAGE.id,
        locale: "de",
        proposals: 0,
        outcome: "draft",
        reason: null,
        excluded: null,
      },
    ],
  });
  api.orderTranslation.mockResolvedValue({ id: "job-1", state: "queued" });
  api.getTranslationJob.mockResolvedValue({ id: "job-1", state: "partial" });
  show();

  const again = () =>
    screen.findByRole("button", { name: "Przetłumacz brakujące (AI)" });
  fireEvent.click(await again());
  fireEvent.click(await screen.findByRole("button", { name: "Przetłumacz" }));
  expect(
    await screen.findByText(
      "Tłumaczenie gotowe częściowo — część fragmentów wymaga Twojej uwagi.",
    ),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));

  fireEvent.click(await again());
  // The dialog asks what it would cost now; it does not show the old order.
  expect(
    await screen.findByRole("button", { name: "Przetłumacz" }),
  ).not.toBeNull();
  expect(api.quoteTranslation).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByText(
      "Tłumaczenie gotowe częściowo — część fragmentów wymaga Twojej uwagi.",
    ),
  ).toBeNull();
});

test("the address dialog shows what a search engine reads of this version", async () => {
  api.getLocaleBody.mockResolvedValue(body());
  api.listPageTranslations.mockResolvedValue({
    page_id: PAGE.id,
    items: [{ locale: "de", slug: "angebot", title: "Angebot", version: 4 }],
  });
  api.readSeoPreview.mockResolvedValue({
    public: true,
    reason: "",
    url: "https://studio.example.test/de/angebot/",
    title: "Angebot",
    description: "",
    site_name: "Studio",
    noindex: false,
    hreflang: {},
    structured_data: {},
  });
  show();

  await screen.findByText("1. Baner powitalny");
  fireEvent.click(screen.getByRole("button", { name: "Więcej" }));
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Adres i opis" }),
  );

  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByRole("heading", {
      name: "Podgląd w wyszukiwarce",
    }),
  ).not.toBeNull();
  expect(
    await within(dialog).findByText(
      "Studio · https://studio.example.test/de/angebot/",
    ),
  ).not.toBeNull();
  // This page, this language.
  expect(api.readSeoPreview).toHaveBeenCalledWith(PAGE.site_id, PAGE.id, "de");
});
