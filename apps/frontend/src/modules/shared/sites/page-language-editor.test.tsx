import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function show(locale: "pl" | "en" = "pl") {
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
        languageSwitch={null}
        onSwitchToSource={vi.fn()}
        onChanged={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
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
