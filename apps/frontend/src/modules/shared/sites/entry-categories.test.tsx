import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type ContentEntry,
  type Term,
  type TermList,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { EntryCategories } from "./entry-categories";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const { createTerm, listTerms, setContentEntryCategories } = vi.hoisted(() => ({
  createTerm: vi.fn(),
  listTerms: vi.fn(),
  setContentEntryCategories: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createTerm,
  listTerms,
  setContentEntryCategories,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const collectionId = "019ff20d-a000-7000-8000-000000000020";

const term = (key: string, name: string, extra: Partial<Term> = {}): Term => ({
  id: `term-${key}`,
  key,
  name,
  parent_id: null,
  position: 0,
  depth: 1,
  names: {},
  slugs: { pl: key },
  paths: { pl: `/blog/kategoria/${key}/` },
  locked: [],
  entries: 0,
  entries_elsewhere: 0,
  published: {},
  removable: true,
  ...extra,
});
const care = term("pielegnacja", "Pielęgnacja");
const winter = term("zima", "Zima", { parent_id: care.id, depth: 2 });
const advice = term("porady", "Porady");

const listOf = (terms: Term[], maxPerEntry = 10): TermList => ({
  kind: "categories",
  collection_id: collectionId,
  taxonomy_id: "tax",
  default_locale: "pl",
  locales: ["pl"],
  segments: { pl: "kategoria" },
  max_depth: 3,
  max_per_entry: maxPerEntry,
  terms,
});

const entry = (categories: ContentEntry["categories"] = []): ContentEntry =>
  ({
    id: "019ff20d-a000-7000-8000-000000000030",
    collection_id: collectionId,
    title: "Pierwszy wpis",
    tags: [],
    categories,
  }) as unknown as ContentEntry;

function renderCard(
  value: ContentEntry,
  onChanged = vi.fn().mockResolvedValue(undefined),
  locale: "pl" | "en" = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <EntryCategories entry={value} onChanged={onChanged} siteId={siteId} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listTerms.mockResolvedValue(listOf([care, winter, advice]));
  setContentEntryCategories.mockResolvedValue([]);
});

test("shows the type's tree as checkboxes, ticked from the entry, and links to managing them", async () => {
  const rendered = renderCard(
    entry([{ id: winter.id, key: "zima", name: "Zima", parent_id: care.id }]),
  );

  const winterBox = (await screen.findByRole("checkbox", {
    name: "Zima",
  })) as HTMLInputElement;
  expect(listTerms).toHaveBeenCalledWith(collectionId, "categories");
  expect(winterBox.checked).toBe(true);
  expect(
    (screen.getByRole("checkbox", { name: "Pielęgnacja" }) as HTMLInputElement)
      .checked,
  ).toBe(false);
  // A level further in stands further in.
  expect(
    (winterBox.closest("label") as HTMLElement).style.paddingInlineStart,
  ).toBe("1.25rem");
  expect(
    screen.getByText(
      "Zmianę kategorii widać na stronie po ponownym opublikowaniu wpisu.",
    ),
  ).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Zarządzaj kategoriami" }),
  ).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${collectionId}/categories?site=${siteId}`,
    ),
  );
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("saves the whole ticked set, in the tree's order, and asks the page to read the entry again", async () => {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  renderCard(entry(), onChanged);

  fireEvent.click(await screen.findByRole("checkbox", { name: "Porady" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Zima" }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz kategorie" }));

  await waitFor(() =>
    expect(setContentEntryCategories).toHaveBeenCalledWith(entry().id, [
      winter.id,
      advice.id,
    ]),
  );
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("at the limit the rest are disabled and the limit is said", async () => {
  listTerms.mockResolvedValue(listOf([care, winter, advice], 2));
  renderCard(
    entry([
      { id: care.id, key: "pielegnacja", name: "Pielęgnacja", parent_id: null },
      { id: winter.id, key: "zima", name: "Zima", parent_id: care.id },
    ]),
  );

  const free = (await screen.findByRole("checkbox", {
    name: "Porady",
  })) as HTMLInputElement;
  expect(free.disabled).toBe(true);
  expect(
    screen.getByText("Wpis może mieć najwyżej 2 kategorie."),
  ).not.toBeNull();
  // A ticked one can still be unticked, which frees the rest.
  const ticked = screen.getByRole("checkbox", {
    name: "Zima",
  }) as HTMLInputElement;
  expect(ticked.disabled).toBe(false);
  fireEvent.click(ticked);
  expect(free.disabled).toBe(false);
  expect(screen.queryByText(/najwyżej 2 kategorie/)).toBeNull();
});

test("makes a category in place at the top and ticks it", async () => {
  const made = term("dieta", "Dieta");
  createTerm.mockResolvedValue(made);
  renderCard(entry());
  await screen.findByRole("checkbox", { name: "Porady" });
  listTerms.mockResolvedValue(listOf([care, winter, advice, made]));

  fireEvent.change(screen.getByLabelText("Nowa kategoria"), {
    target: { value: " Dieta " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));

  await waitFor(() =>
    expect(createTerm).toHaveBeenCalledWith(collectionId, {
      kind: "categories",
      name: "Dieta",
    }),
  );
  const box = (await screen.findByRole("checkbox", {
    name: "Dieta",
  })) as HTMLInputElement;
  await waitFor(() => expect(box.checked).toBe(true));
  expect(
    (screen.getByLabelText("Nowa kategoria") as HTMLInputElement).value,
  ).toBe("");
  // Making it is not yet filing the entry under it.
  expect(setContentEntryCategories).not.toHaveBeenCalled();
});

test("a type without categories says so and still offers the add row", async () => {
  listTerms.mockResolvedValue(listOf([]));
  renderCard(entry());

  expect(
    await screen.findByText("Ten typ treści nie ma jeszcze kategorii."),
  ).not.toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByLabelText("Nowa kategoria")).not.toBeNull();
  expect(screen.getByRole("button", { name: "Dodaj" })).not.toBeNull();
});

test("a refusal is said under the card, in English too", async () => {
  setContentEntryCategories.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "x",
      status: 400,
      code: "entry_too_many_categories",
      detail: "po polsku",
      correlation_id: null,
      errors: [],
    }),
  );
  renderCard(entry(), undefined, "en");

  fireEvent.click(
    await screen.findByRole("button", { name: "Save categories" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "An entry takes at most ten categories.",
  );
});
