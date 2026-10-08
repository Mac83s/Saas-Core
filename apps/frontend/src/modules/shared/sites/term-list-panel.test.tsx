import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type ContentCollection,
  type ContentTypes,
  type Term,
  type TermChange,
  type TermList,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CreateCategoryDialog, TermListPanel } from "./term-list-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const {
  createTerm,
  deleteTerm,
  getPublicLocales,
  listContentTypes,
  listTerms,
  previewTermAddress,
  previewTermRemoval,
  previewTermUpdate,
  setTermAddress,
  setTermNames,
  updateTerm,
} = vi.hoisted(() => ({
  createTerm: vi.fn(),
  deleteTerm: vi.fn(),
  getPublicLocales: vi.fn(),
  listContentTypes: vi.fn(),
  listTerms: vi.fn(),
  previewTermAddress: vi.fn(),
  previewTermRemoval: vi.fn(),
  previewTermUpdate: vi.fn(),
  setTermAddress: vi.fn(),
  setTermNames: vi.fn(),
  updateTerm: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createTerm,
  deleteTerm,
  getPublicLocales,
  listContentTypes,
  listTerms,
  previewTermAddress,
  previewTermRemoval,
  previewTermUpdate,
  setTermAddress,
  setTermNames,
  updateTerm,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const typeId = "019ff20d-a000-7000-8000-000000000020";
const address = "https://studio.example.test";

const blog: ContentCollection = {
  id: typeId,
  site_id: siteId,
  key: "blog",
  name: "Blog",
  kind: "blog",
  base_path: "blog",
  locale_paths: {},
  paths: { pl: "/blog/", en: "/en/blog/" },
  automation_policy: "manual",
  show_in_navigation: true,
  schema_type: "BlogPosting",
  in_site_feed: true,
  archived: false,
  archived_at: null,
};

function term(
  key: string,
  name: string,
  extra: Partial<Term> & { slug?: string; enSlug?: string } = {},
): Term {
  const { slug = key, enSlug = key, ...rest } = extra;
  const depth = rest.depth ?? 1;
  const parentPath = rest.parent_id
    ? "/blog/kategoria/pielegnacja/"
    : "/blog/kategoria/";
  return {
    id: `term-${key}`,
    key,
    name,
    parent_id: null,
    position: 0,
    depth,
    names: {},
    slugs: { pl: slug, en: enSlug },
    paths: {
      pl: `${parentPath}${slug}/`,
      en: `/en/blog/category/${enSlug}/`,
    },
    locked: [],
    entries: 0,
    entries_elsewhere: 0,
    published: {},
    removable: true,
    ...rest,
  };
}

// In tree order: a category, then those under it, by position.
const care = term("pielegnacja", "Pielęgnacja", {
  entries: 5,
  published: { pl: 3, en: 1 },
  names: { en: { text: "Care", origin: "ai", state: "stale" } },
});
const winter = term("zima", "Zima", {
  parent_id: care.id,
  depth: 2,
  position: 0,
  entries: 2,
  published: { pl: 2 },
});
const summer = term("lato", "Lato", {
  parent_id: care.id,
  depth: 2,
  position: 1,
});
const advice = term("porady", "Porady", { position: 1 });

function listOf(
  terms: Term[],
  kind: "categories" | "tags" = "categories",
): TermList {
  return {
    kind,
    collection_id: typeId,
    taxonomy_id: "tax",
    default_locale: "pl",
    locales: ["pl", "en"],
    segments: { pl: "kategoria", en: "category" },
    max_depth: 3,
    max_per_entry: 10,
    terms,
  };
}

const types: ContentTypes = {
  types: [
    { collection: blog, entries: 7, published: 4, locales: ["pl", "en"] },
  ],
  limit: {
    allowed: true,
    code: "",
    message: "",
    offered: true,
    additional_max: 10,
    additional_used: 0,
  },
  schema_types: [],
};

function change(of: Term, extra: Partial<TermChange> = {}): TermChange {
  return {
    term: of,
    changed: true,
    moved: [],
    takes_over: [],
    published: 0,
    ...extra,
  };
}

function problem(code: string) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Żądanie nie może zostać obsłużone",
    status: 400,
    code,
    detail: "Odmowa po polsku.",
    correlation_id: null,
    errors: [],
  });
}

function renderIn(
  node: React.ReactNode,
  locale: "pl" | "en" = "pl",
): ReturnType<typeof render> {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      {node}
    </NextIntlClientProvider>,
  );
}

function panel(kind: "categories" | "tags" = "categories", onLoaded = vi.fn()) {
  return (
    <TermListPanel
      address={address}
      kind={kind}
      onLoaded={onLoaded}
      siteId={siteId}
      typeId={typeId}
    />
  );
}

const row = (name: string) =>
  screen
    .getByText(name, { selector: "p" })
    .closest("tr") as HTMLTableRowElement;

async function openMenu(name: string, label = `Działania dla ${name}`) {
  fireEvent.click(within(row(name)).getByRole("button", { name: label }));
}

beforeEach(() => {
  vi.clearAllMocks();
  listContentTypes.mockResolvedValue(types);
  listTerms.mockResolvedValue(listOf([care, winter, summer, advice]));
  getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en"],
    version: 1,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "en", native_name: "English", english_name: "English" },
    ],
    limit: { allowed: true, additional_max: null, reason: "" },
    protected: {},
  });
  updateTerm.mockImplementation(async (_t: string, _id: string, body: object) =>
    change({ ...care, ...body }),
  );
  setTermNames.mockResolvedValue(change(care));
  previewTermUpdate.mockResolvedValue(change(care));
  previewTermRemoval.mockResolvedValue({
    removable: true,
    removed: false,
    drafts: 0,
    published: 0,
    children: 0,
  });
  deleteTerm.mockResolvedValue({
    removable: true,
    removed: true,
    drafts: 0,
    published: 0,
    children: 0,
  });
  createTerm.mockResolvedValue(care);
});

test("lists the categories in tree order, indented, with what each shows on the site", async () => {
  const onLoaded = vi.fn();
  const rendered = renderIn(panel("categories", onLoaded));

  await screen.findByText("Pielęgnacja", { selector: "p" });
  const names = screen
    .getAllByRole("row")
    .slice(1)
    .map((item) => within(item).getAllByRole("cell")[0]?.textContent);
  expect(names).toEqual(["Pielęgnacja", "Zima", "Lato", "Porady"]);
  expect(onLoaded).toHaveBeenCalledWith(blog);
  expect(listTerms).toHaveBeenCalledWith(typeId, "categories");

  // Two levels down the tree stand further in than the top.
  const indent = (name: string) =>
    (screen.getByText(name, { selector: "p" }) as HTMLElement).style
      .paddingInlineStart;
  expect(indent("Pielęgnacja")).toBe("0rem");
  expect(indent("Zima")).toBe("1.25rem");

  // A category with published entries is a link opening in a new tab...
  const live = within(row("Pielęgnacja")).getByRole("link", {
    name: "/blog/kategoria/pielegnacja/",
  });
  expect(live.getAttribute("href")).toBe(
    "https://studio.example.test/blog/kategoria/pielegnacja/",
  );
  expect(live.getAttribute("target")).toBe("_blank");
  expect(within(row("Pielęgnacja")).getByText("5 wpisów")).not.toBeNull();
  // ...the sum of the languages' pages.
  expect(within(row("Pielęgnacja")).getByText("na stronie: 4")).not.toBeNull();
  // ...and one without is plain text that says why.
  expect(within(row("Lato")).queryByRole("link")).toBeNull();
  expect(
    within(row("Lato")).getByText("— jeszcze bez wpisów na stronie"),
  ).not.toBeNull();
  expect(
    screen.getByText(/Kategorie porządkują wpisy tego typu treści/),
  ).not.toBeNull();

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("says so when there are no categories", async () => {
  listTerms.mockResolvedValue(listOf([]));
  renderIn(panel());
  expect(
    await screen.findByText("Ten typ treści nie ma jeszcze kategorii."),
  ).not.toBeNull();
});

test("moves a category among those beside it, and offers only the moves that exist", async () => {
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });

  // The first of its level cannot go up; the last cannot go down.
  await openMenu("Zima");
  expect(screen.queryByRole("menuitem", { name: "Przenieś wyżej" })).toBeNull();
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Przenieś niżej" }),
  );
  await waitFor(() =>
    expect(updateTerm).toHaveBeenCalledWith(typeId, winter.id, { position: 1 }),
  );
  // The list is read again.
  await waitFor(() => expect(listTerms).toHaveBeenCalledTimes(2));

  await openMenu("Lato");
  expect(screen.queryByRole("menuitem", { name: "Przenieś niżej" })).toBeNull();
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Przenieś wyżej" }),
  );
  await waitFor(() =>
    expect(updateTerm).toHaveBeenCalledWith(typeId, summer.id, { position: 0 }),
  );
});

test("editing sends the name and place that changed, then only the names that changed, and keeps a note on a moved page", async () => {
  updateTerm.mockResolvedValue(
    change(
      { ...care, name: "Pielęgnacja włosów" },
      {
        moved: [
          {
            locale: "pl",
            from_path: "/blog/kategoria/pielegnacja/",
            to_path: "/blog/kategoria/pielegnacja-wlosow/",
          },
        ],
      },
    ),
  );
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });

  fireEvent.click(
    within(row("Pielęgnacja")).getByRole("button", { name: "Edytuj" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText("Edytuj kategorię „Pielęgnacja”"),
  ).not.toBeNull();
  // The other language's name comes prefilled, with what it came from.
  const english = within(dialog).getByLabelText(
    "Nazwa — English",
  ) as HTMLInputElement;
  expect(english.value).toBe("Care");
  expect(
    within(dialog).getByText(
      /Przetłumaczone automatycznie\. Wpisana tu nazwa nie będzie już nadpisywana\./,
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      /Nazwa w języku strony zmieniła się od czasu tego tłumaczenia\./,
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      "Zmianę nazwy i miejsca w drzewie widać na stronie od razu, bez publikowania wpisów.",
    ),
  ).not.toBeNull();
  // A category is not offered as its own parent, nor anything under it.
  const parent = within(dialog).getByLabelText(
    "Kategoria nadrzędna",
  ) as HTMLSelectElement;
  expect([...parent.options].map((option) => option.value)).toEqual([
    "",
    advice.id,
  ]);
  expect((await axe.run(dialog)).violations).toHaveLength(0);

  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Pielęgnacja włosów" },
  });
  fireEvent.change(english, { target: { value: "Hair care" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));

  await waitFor(() =>
    expect(updateTerm).toHaveBeenCalledWith(typeId, care.id, {
      name: "Pielęgnacja włosów",
    }),
  );
  await waitFor(() =>
    expect(setTermNames).toHaveBeenCalledWith(typeId, care.id, {
      en: "Hair care",
    }),
  );
  // Told on the page, not in a toast that goes.
  const note = await screen.findByRole("status");
  expect(note.textContent).toBe(
    "Strona tej kategorii w języku Polski ma teraz adres /blog/kategoria/pielegnacja-wlosow/. Stary adres /blog/kategoria/pielegnacja/ przekierowuje na nowy.",
  );
});

test("saving only another language's name does not touch the term itself", async () => {
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  fireEvent.click(
    within(row("Pielęgnacja")).getByRole("button", { name: "Edytuj" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Nazwa — English"), {
    target: { value: "" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));

  // An emptied name removes that language's.
  await waitFor(() =>
    expect(setTermNames).toHaveBeenCalledWith(typeId, care.id, { en: "" }),
  );
  expect(updateTerm).not.toHaveBeenCalled();
});

test("moving a category under another says how many published entries reach the pages above", async () => {
  previewTermUpdate.mockResolvedValue(change(summer, { published: 3 }));
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  fireEvent.click(within(row("Lato")).getByRole("button", { name: "Edytuj" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).queryByRole("status")).toBeNull();

  fireEvent.change(within(dialog).getByLabelText("Kategoria nadrzędna"), {
    target: { value: advice.id },
  });

  expect(
    await within(dialog).findByText(
      "3 opublikowane wpisy pojawią się od razu na stronach kategorii nadrzędnych.",
    ),
  ).not.toBeNull();
  expect(previewTermUpdate).toHaveBeenCalledWith(typeId, summer.id, {
    parent_id: advice.id,
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(updateTerm).toHaveBeenCalledWith(typeId, summer.id, {
      parent_id: advice.id,
    }),
  );
});

test("a name the server refuses is said in the dialog, which stays open", async () => {
  updateTerm.mockRejectedValue(problem("term_name_taken"));
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  fireEvent.click(
    within(row("Pielęgnacja")).getByRole("button", { name: "Edytuj" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Porady" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));

  expect(
    await within(dialog).findByText("Obok jest już pozycja o tej nazwie."),
  ).not.toBeNull();
  expect(setTermNames).not.toHaveBeenCalled();
});

test("a new address shows the path being built, what moves, and wants a reason before it moves a page that works", async () => {
  previewTermAddress.mockResolvedValue(
    change(care, {
      moved: [
        {
          locale: "pl",
          from_path: "/blog/kategoria/pielegnacja/",
          to_path: "/blog/kategoria/wlosy/",
        },
      ],
    }),
  );
  setTermAddress.mockResolvedValue(
    change(care, {
      moved: [
        {
          locale: "pl",
          from_path: "/blog/kategoria/pielegnacja/",
          to_path: "/blog/kategoria/wlosy/",
        },
      ],
    }),
  );
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  await openMenu("Pielęgnacja");
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Zmień adres…" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(
      "Adres zmieniaj tylko wtedy, gdy to konieczne — wyszukiwarki znają stary. Stary adres będzie przekierowywać na nowy.",
    ),
  ).not.toBeNull();
  // Nothing to ask until the address differs.
  expect(
    (
      within(dialog).getByRole("button", {
        name: "Zmień adres",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  // The path as it will stand, in front of what is typed.
  expect(
    within(dialog).getByText("studio.example.test/blog/kategoria/"),
  ).not.toBeNull();

  fireEvent.change(within(dialog).getByLabelText("Adres"), {
    target: { value: "wlosy" },
  });
  expect(
    await within(dialog).findByText(
      "Te adresy przestaną odpowiadać i będą przekierowywać:",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      "/blog/kategoria/pielegnacja/ → /blog/kategoria/wlosy/",
    ),
  ).not.toBeNull();
  expect(previewTermAddress).toHaveBeenCalledWith(typeId, care.id, {
    locale: "pl",
    slug: "wlosy",
    reason: "",
    take_over_former: false,
  });

  // The reason is required once a page that works moves.
  const submit = within(dialog).getByRole("button", { name: "Zmień adres" });
  fireEvent.click(submit);
  expect(
    await within(dialog).findByText(
      "Ta zmiana przenosi adresy, które już działają. Podaj powód.",
    ),
  ).not.toBeNull();
  expect(setTermAddress).not.toHaveBeenCalled();

  fireEvent.change(
    within(dialog).getByLabelText("Powód zmiany (zostaje w historii)"),
    { target: { value: "Nowa nazwa w ofercie" } },
  );
  fireEvent.click(submit);
  await waitFor(() =>
    expect(setTermAddress).toHaveBeenCalledWith(typeId, care.id, {
      locale: "pl",
      slug: "wlosy",
      reason: "Nowa nazwa w ofercie",
      take_over_former: false,
    }),
  );
  expect((await screen.findByRole("status")).textContent).toContain(
    "ma teraz adres /blog/kategoria/wlosy/",
  );
});

test("an address another term redirects from needs a ticked confirmation", async () => {
  previewTermAddress.mockResolvedValue(
    change(summer, {
      takes_over: [{ slug: "zimno", term_id: winter.id, name: "Zima" }],
    }),
  );
  setTermAddress.mockResolvedValue(change(summer));
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  await openMenu("Lato");
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Zmień adres…" }),
  );
  const dialog = await screen.findByRole("dialog");
  // The other language's address is a choice of the language.
  fireEvent.change(within(dialog).getByLabelText("Język"), {
    target: { value: "en" },
  });
  expect(
    (within(dialog).getByLabelText("Adres") as HTMLInputElement).value,
  ).toBe("lato");
  fireEvent.change(within(dialog).getByLabelText("Adres"), {
    target: { value: "zimno" },
  });
  const box = await within(dialog).findByRole("checkbox", {
    name: "Adres „zimno” przekierowuje dziś do „Zima”. Po zmianie to przekierowanie przestanie działać.",
  });
  // No moved page, so no reason is asked for.
  expect(
    within(dialog).queryByLabelText("Powód zmiany (zostaje w historii)"),
  ).toBeNull();

  fireEvent.click(within(dialog).getByRole("button", { name: "Zmień adres" }));
  expect(
    await within(dialog).findByText(
      "Potwierdź, że przekierowanie ma przestać działać.",
    ),
  ).not.toBeNull();
  expect(setTermAddress).not.toHaveBeenCalled();

  fireEvent.click(box);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zmień adres" }));
  await waitFor(() =>
    expect(setTermAddress).toHaveBeenCalledWith(typeId, summer.id, {
      locale: "en",
      slug: "zimno",
      reason: "",
      take_over_former: true,
    }),
  );
});

test("an address the server refuses is said in the dialog", async () => {
  previewTermAddress.mockRejectedValue(problem("term_slug_taken"));
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  await openMenu("Lato");
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Zmień adres…" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Adres"), {
    target: { value: "porady" },
  });
  expect(
    await within(dialog).findByText("Ten adres jest już zajęty."),
  ).not.toBeNull();
  expect(
    (
      within(dialog).getByRole("button", {
        name: "Zmień adres",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

test("a category something carries cannot be removed, and the dialog says what carries it", async () => {
  previewTermRemoval.mockResolvedValue({
    removable: false,
    removed: false,
    drafts: 2,
    published: 1,
    children: 0,
  });
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  await openMenu("Pielęgnacja");
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń…" }));
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText("Nie można usunąć „Pielęgnacja”"),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      "Wpisy przypisane w panelu: 2. Opublikowane wpisy, które pokazują ją na stronie: 1. Zdejmij ją z tych wpisów i opublikuj je ponownie — wtedy da się ją usunąć.",
    ),
  ).not.toBeNull();
  expect(within(dialog).queryByRole("button", { name: "Usuń" })).toBeNull();
  expect(
    within(dialog).getAllByRole("button", { name: "Zamknij" }),
  ).not.toHaveLength(0);
  expect(deleteTerm).not.toHaveBeenCalled();
});

test("a free category is removed after the preview, and its children move one level up", async () => {
  previewTermRemoval.mockResolvedValue({
    removable: true,
    removed: false,
    drafts: 0,
    published: 0,
    children: 2,
  });
  renderIn(panel());
  await screen.findByText("Pielęgnacja", { selector: "p" });
  await openMenu("Pielęgnacja");
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń…" }));
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText("Usunąć „Pielęgnacja”?"),
  ).not.toBeNull();
  expect(within(dialog).getByText("Jej adres będzie wolny.")).not.toBeNull();
  expect(
    within(dialog).getByText(
      "Kategorie, które leżą pod nią (2), przejdą poziom wyżej.",
    ),
  ).not.toBeNull();
  expect((await axe.run(dialog)).violations).toHaveLength(0);
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń" }));

  await waitFor(() => expect(deleteTerm).toHaveBeenCalledWith(typeId, care.id));
  await waitFor(() => expect(listTerms).toHaveBeenCalledTimes(2));
});

test("tags: no new action, no parent, no moves; says where else a tag is carried; English too", async () => {
  const tag = term("porady", "Porady", {
    entries: 2,
    entries_elsewhere: 3,
    published: { pl: 1 },
    paths: { pl: "/blog/tag/porady/", en: "/en/blog/tag/porady/" },
  });
  const other = term("dieta", "Dieta", { position: 1 });
  listTerms.mockResolvedValue(listOf([tag, other], "tags"));
  const rendered = renderIn(panel("tags"), "en");

  await screen.findByText("Porady", { selector: "p" });
  expect(listTerms).toHaveBeenCalledWith(typeId, "tags");
  expect(
    screen.getByText(/Tags belong to the whole site: one tag can mark entries/),
  ).not.toBeNull();
  expect(
    within(row("Porady")).getByText("in other content types: 3"),
  ).not.toBeNull();
  expect(within(row("Porady")).getByText("on the site: 1")).not.toBeNull();
  expect(
    within(row("Dieta")).getByText("— no entries on the site yet"),
  ).not.toBeNull();

  fireEvent.click(
    within(row("Dieta")).getByRole("button", { name: "Actions for Dieta" }),
  );
  await screen.findByRole("menuitem", { name: "Change address…" });
  expect(screen.queryByRole("menuitem", { name: "Move up" })).toBeNull();
  expect(screen.queryByRole("menuitem", { name: "Move down" })).toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, {
    key: "Escape",
  });

  fireEvent.click(within(row("Dieta")).getByRole("button", { name: "Edit" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Edit the tag “Dieta”")).not.toBeNull();
  expect(within(dialog).queryByLabelText("Parent category")).toBeNull();
  expect(within(dialog).getByLabelText("Name — English")).not.toBeNull();
  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);
});

test("a site with no tags says where they come from", async () => {
  listTerms.mockResolvedValue(listOf([], "tags"));
  renderIn(panel("tags"));
  expect(
    await screen.findByText(
      "Strona nie ma jeszcze tagów. Dodasz je przy wpisie.",
    ),
  ).not.toBeNull();
});

test("a type that is not there says so", async () => {
  listContentTypes.mockResolvedValue({ ...types, types: [] });
  renderIn(panel());
  expect(
    await screen.findByText("Tego typu treści nie ma — mógł zostać usunięty."),
  ).not.toBeNull();
});

test("a new category takes a name and a parent that has room below it", async () => {
  const deep = term("gleboka", "Głęboka", {
    parent_id: winter.id,
    depth: 3,
  });
  listTerms.mockResolvedValue(listOf([care, winter, deep, advice]));
  const onCreated = vi.fn();
  renderIn(<CreateCategoryDialog onCreated={onCreated} typeId={typeId} />);

  fireEvent.click(screen.getByRole("button", { name: "Nowa kategoria" }));
  const dialog = await screen.findByRole("dialog");
  const parent = (await waitFor(() => {
    const select = within(dialog).getByLabelText(
      "Kategoria nadrzędna",
    ) as HTMLSelectElement;
    expect(select.options.length).toBeGreaterThan(1);
    return select;
  })) as HTMLSelectElement;
  // A category on the last level has no room for another beneath it.
  expect([...parent.options].map((option) => option.value)).toEqual([
    "",
    care.id,
    winter.id,
    advice.id,
  ]);
  expect(parent.options[0]?.textContent).toBe("Brak — najwyższy poziom");
  expect((await axe.run(dialog)).violations).toHaveLength(0);

  // A name is required.
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Nowa kategoria" }),
  );
  expect(
    await within(dialog).findByText("To pole jest wymagane."),
  ).not.toBeNull();
  expect(createTerm).not.toHaveBeenCalled();

  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "  Dieta  " },
  });
  fireEvent.change(parent, { target: { value: care.id } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Nowa kategoria" }),
  );

  await waitFor(() =>
    expect(createTerm).toHaveBeenCalledWith(typeId, {
      kind: "categories",
      name: "Dieta",
      parent_id: care.id,
    }),
  );
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
});

test("a new category at the top sends no parent", async () => {
  renderIn(<CreateCategoryDialog onCreated={vi.fn()} typeId={typeId} />, "en");
  fireEvent.click(screen.getByRole("button", { name: "New category" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), {
    target: { value: "Diet" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "New category" }));

  await waitFor(() =>
    expect(createTerm).toHaveBeenCalledWith(typeId, {
      kind: "categories",
      name: "Diet",
    }),
  );
});
