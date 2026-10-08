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
  type ContentTypeSwitch,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { ContentTypeSettings } from "./content-type-settings";
import {
  ContentTypesPanel,
  CreateContentTypeDialog,
} from "./content-types-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const {
  createContentCollection,
  deleteContentType,
  getPublicLocales,
  listContentTypes,
  previewCollectionPaths,
  previewContentTypeSwitchOff,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  setCollectionPaths,
  switchOffContentType,
  switchOnContentType,
  updateContentType,
} = vi.hoisted(() => ({
  createContentCollection: vi.fn(),
  deleteContentType: vi.fn(),
  getPublicLocales: vi.fn(),
  listContentTypes: vi.fn(),
  previewCollectionPaths: vi.fn(),
  previewContentTypeSwitchOff: vi.fn(),
  setCollectionAutomationPolicy: vi.fn(),
  setCollectionNavigation: vi.fn(),
  setCollectionPaths: vi.fn(),
  switchOffContentType: vi.fn(),
  switchOnContentType: vi.fn(),
  updateContentType: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createContentCollection,
  deleteContentType,
  getPublicLocales,
  listContentTypes,
  previewCollectionPaths,
  previewContentTypeSwitchOff,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  setCollectionPaths,
  switchOffContentType,
  switchOnContentType,
  updateContentType,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";

const blog: ContentCollection = {
  id: "019ff20d-a000-7000-8000-000000000020",
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
const projects: ContentCollection = {
  ...blog,
  id: "019ff20d-a000-7000-8000-000000000021",
  key: "realizacje",
  name: "Realizacje",
  base_path: "realizacje",
  locale_paths: { en: "projects" },
  paths: { pl: "/realizacje/", en: "/en/projects/" },
  show_in_navigation: false,
  schema_type: "WebPage",
  in_site_feed: false,
};
const news: ContentCollection = {
  ...blog,
  id: "019ff20d-a000-7000-8000-000000000022",
  key: "aktualnosci",
  name: "Aktualności",
  base_path: "aktualnosci",
  paths: { pl: "/aktualnosci/", en: "/en/aktualnosci/" },
  archived: true,
  archived_at: "2026-10-08T10:00:00Z",
};

const schemaTypes: ContentTypes["schema_types"] = [
  {
    schema_type: "BlogPosting",
    title: { pl: "Wpisy bloga", en: "Blog posts" },
    hint: { pl: "Artykuły i porady.", en: "Articles and tips." },
    in_site_feed: true,
  },
  {
    schema_type: "WebPage",
    title: { pl: "Zwykłe strony", en: "Plain pages" },
    hint: { pl: "Realizacje, oferty, miejsca.", en: "Projects, offers." },
    in_site_feed: false,
  },
];

function found(limit: Partial<ContentTypes["limit"]> = {}): ContentTypes {
  return {
    types: [
      { collection: blog, entries: 12, published: 9, locales: ["pl", "en"] },
      { collection: projects, entries: 3, published: 2, locales: ["pl"] },
      { collection: news, entries: 0, published: 0, locales: [] },
    ],
    limit: {
      allowed: true,
      code: "",
      message: "",
      offered: true,
      additional_max: 10,
      additional_used: 1,
      ...limit,
    },
    schema_types: schemaTypes,
  };
}

const switchPreview: ContentTypeSwitch = {
  collection: projects,
  changed: true,
  published: 2,
  scheduled: 1,
  paths: { pl: "/realizacje/", en: "/en/projects/" },
  restorable: true,
  restore_problem: "",
  restore_problem_code: "",
};

function problem(
  code: string,
  errors: { field: string | null; code: string; message: string }[] = [],
) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Żądanie nie może zostać obsłużone",
    status: 400,
    code,
    detail: "Odmowa po polsku.",
    correlation_id: null,
    errors,
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

const row = (name: string) =>
  screen.getByText(name).closest("tr") as HTMLTableRowElement;

beforeEach(() => {
  vi.clearAllMocks();
  listContentTypes.mockResolvedValue(found());
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
  previewContentTypeSwitchOff.mockResolvedValue(switchPreview);
  switchOffContentType.mockResolvedValue({
    ...switchPreview,
    collection: { ...projects, archived: true },
  });
  switchOnContentType.mockResolvedValue({
    ...switchPreview,
    collection: { ...news, archived: false },
  });
  deleteContentType.mockResolvedValue(undefined);
  createContentCollection.mockResolvedValue(projects);
  updateContentType.mockImplementation(
    async (_id: string, input: Partial<ContentCollection>) => ({
      ...projects,
      ...input,
    }),
  );
});

test("lists the site's types with the blog first, and stays accessible", async () => {
  const rendered = renderIn(<ContentTypesPanel siteId={siteId} />);

  expect(await screen.findByText("Realizacje")).not.toBeNull();
  const names = screen
    .getAllByRole("row")
    .slice(1)
    .map((item) => within(item).getAllByRole("cell")[0]?.textContent);
  expect(names).toEqual(["Blog", "Realizacje"]);
  // What a company reads about a type: where it answers, how much is in it.
  expect(within(row("Realizacje")).getByText("/realizacje/")).not.toBeNull();
  expect(within(row("Realizacje")).getByText("/en/projects/")).not.toBeNull();
  expect(within(row("Realizacje")).getByText("3 wpisy")).not.toBeNull();
  expect(within(row("Realizacje")).getByText("na stronie: 2")).not.toBeNull();
  expect(within(row("Blog")).getByText("12 wpisów")).not.toBeNull();
  expect(within(row("Blog")).getByText("PL, EN")).not.toBeNull();
  expect(
    screen.getByText(
      "Twój plan: 1 z 10 typów treści poza pierwszym na tej stronie.",
    ),
  ).not.toBeNull();
  // A switched-off type is not among the ones that are on.
  expect(screen.queryByText("Aktualności")).toBeNull();
  expect(
    within(row("Realizacje")).getByRole("link", { name: "Wpisy" }),
  ).toHaveProperty(
    "href",
    expect.stringContaining(
      `/panel/sites/content/${projects.id}?site=${siteId}`,
    ),
  );

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("a switched-off type waits under its filter, to be switched on or removed", async () => {
  renderIn(<ContentTypesPanel siteId={siteId} />);
  await screen.findByText("Realizacje");

  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "off" },
  });

  expect(await screen.findByText("Aktualności")).not.toBeNull();
  expect(screen.queryByText("Realizacje")).toBeNull();
  expect(within(row("Aktualności")).getByText("Wyłączony")).not.toBeNull();
  listContentTypes.mockResolvedValue({
    ...found(),
    types: found().types.map((item) =>
      item.collection.id === news.id
        ? { ...item, collection: { ...news, archived: false } }
        : item,
    ),
  });
  fireEvent.click(
    within(row("Aktualności")).getByRole("button", { name: "Włącz" }),
  );

  await waitFor(() =>
    expect(switchOnContentType).toHaveBeenCalledWith(news.id),
  );
  expect(
    await screen.findByText(
      "Typ treści „Aktualności” jest znów na stronie, pod tymi samymi adresami.",
    ),
  ).not.toBeNull();
  // Back among the types that are on.
  expect(await screen.findByText("Realizacje")).not.toBeNull();
  expect(screen.getByText("Aktualności")).not.toBeNull();
});

test("says in the company's words why a type cannot be switched on", async () => {
  switchOnContentType.mockRejectedValue(problem("quota_exceeded"));
  renderIn(<ContentTypesPanel siteId={siteId} />);
  await screen.findByText("Realizacje");
  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "off" },
  });

  fireEvent.click(
    within(await screen.findByRole("table")).getByRole("button", {
      name: "Włącz",
    }),
  );

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(
    "Twój plan nie obejmuje kolejnego typu treści na tej stronie.",
  );
  expect(alert.textContent).not.toContain("Odmowa po polsku");
});

test("switching off says what stops answering and what stays, before it is done", async () => {
  previewContentTypeSwitchOff.mockResolvedValue({
    ...switchPreview,
    restorable: false,
    restore_problem: "Plan nie obejmuje kolejnego typu treści.",
    restore_problem_code: "quota_exceeded",
  });
  renderIn(<ContentTypesPanel siteId={siteId} />);
  await screen.findByText("Realizacje");

  fireEvent.click(
    within(row("Realizacje")).getByRole("button", {
      name: "Działania dla typu Realizacje",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Wyłącz" }));

  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText("Wyłączyć typ treści „Realizacje”?"),
  ).not.toBeNull();
  expect(await within(dialog).findByText("/en/projects/")).not.toBeNull();
  expect(
    within(dialog).getByText("Znikną ze strony 2 opublikowane wpisy."),
  ).not.toBeNull();
  expect(
    within(dialog).getByText("Zaplanowana publikacja (1) zostanie odwołana."),
  ).not.toBeNull();
  expect(within(dialog).getByText(/Nic nie zostanie usunięte/)).not.toBeNull();
  // A site over its limit is told the type would not come back.
  expect(
    within(dialog).getByText(/na obecnym planie nie włączysz tego typu/),
  ).not.toBeNull();
  expect(switchOffContentType).not.toHaveBeenCalled();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Wyłącz typ treści" }),
  );

  await waitFor(() =>
    expect(switchOffContentType).toHaveBeenCalledWith(projects.id),
  );
  expect(
    await screen.findByText(/Typ treści „Realizacje” jest wyłączony/),
  ).not.toBeNull();
});

test("only a type without entries offers removal", async () => {
  renderIn(<ContentTypesPanel siteId={siteId} />);
  await screen.findByText("Realizacje");
  fireEvent.click(
    within(row("Realizacje")).getByRole("button", {
      name: "Działania dla typu Realizacje",
    }),
  );
  await screen.findByRole("menuitem", { name: "Wyłącz" });
  expect(screen.queryByRole("menuitem", { name: "Usuń" })).toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, {
    key: "Escape",
  });

  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "off" },
  });
  await screen.findByText("Aktualności");
  fireEvent.click(
    within(row("Aktualności")).getByRole("button", {
      name: "Działania dla typu Aktualności",
    }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń" }));
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/Ten typ nie ma żadnego wpisu/),
  ).not.toBeNull();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Usuń typ treści" }),
  );

  await waitFor(() => expect(deleteContentType).toHaveBeenCalledWith(news.id));
});

test("a new type takes a name, proposes its address and follows the kind into the feed", async () => {
  const onCreated = vi.fn();
  const rendered = renderIn(
    <CreateContentTypeDialog
      address="https://studio.example.test"
      defaultLocale="pl"
      onCreated={onCreated}
      siteId={siteId}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Nowy typ treści" }));
  const name = (await screen.findByLabelText("Nazwa")) as HTMLInputElement;
  expect(name.placeholder).toBe("np. Realizacje");
  fireEvent.change(name, { target: { value: "Realizacje" } });
  const address = screen.getByLabelText("Adres") as HTMLInputElement;
  await waitFor(() => expect(address.value).toBe("realizacje"));
  fireEvent.change(await screen.findByLabelText("Adres: English"), {
    target: { value: "projects" },
  });
  const feed = screen.getByLabelText(
    /Pokazuj wpisy w kanale RSS strony/,
  ) as HTMLInputElement;
  expect(feed.checked).toBe(true);
  // Plain pages are not news for feed readers, until the company says so.
  fireEvent.change(screen.getByLabelText("Czym są wpisy"), {
    target: { value: "WebPage" },
  });
  await waitFor(() => expect(feed.checked).toBe(false));
  expect(screen.getByText(/Realizacje, oferty, miejsca\./)).not.toBeNull();

  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);

  fireEvent.click(screen.getByRole("button", { name: "Dodaj typ treści" }));

  await waitFor(() => expect(createContentCollection).toHaveBeenCalledOnce());
  expect(createContentCollection.mock.calls[0]?.[1]).toEqual({
    key: "realizacje",
    name: "Realizacje",
    kind: "blog",
    base_path: "realizacje",
    locale_paths: { en: "projects" },
    schema_type: "WebPage",
    in_site_feed: false,
  });
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(projects));
});

test("where the plan has no room the dialog says so and offers no form", async () => {
  listContentTypes.mockResolvedValue(
    found({
      allowed: false,
      code: "quota_exceeded",
      message: "Plan nie obejmuje kolejnego typu treści.",
      additional_max: 1,
      additional_used: 1,
    }),
  );
  renderIn(
    <CreateContentTypeDialog onCreated={vi.fn()} siteId={siteId} />,
    "en",
  );

  fireEvent.click(screen.getByRole("button", { name: "New content type" }));

  // In the panel's language, by the code — never the server's sentence.
  expect(
    await screen.findByText(
      "Your plan does not include another content type on this site (limit beyond the first: 1). The types you have keep working. A higher plan gives more.",
    ),
  ).not.toBeNull();
  expect(screen.queryByLabelText("Name")).toBeNull();
  expect(screen.queryByRole("button", { name: "Add content type" })).toBeNull();
});

test("a name the server refuses is said at its field", async () => {
  createContentCollection.mockRejectedValue(
    problem("invalid", [
      {
        field: "base_path",
        code: "section_path_taken",
        message: "Podstrona ma już adres /realizacje/ w języku pl.",
      },
    ]),
  );
  renderIn(<CreateContentTypeDialog onCreated={vi.fn()} siteId={siteId} />);
  fireEvent.click(screen.getByRole("button", { name: "Nowy typ treści" }));
  fireEvent.change(await screen.findByLabelText("Nazwa"), {
    target: { value: "Realizacje" },
  });
  await waitFor(() =>
    expect((screen.getByLabelText("Adres") as HTMLInputElement).value).toBe(
      "realizacje",
    ),
  );

  fireEvent.click(screen.getByRole("button", { name: "Dodaj typ treści" }));

  await waitFor(() => expect(createContentCollection).toHaveBeenCalledOnce());
  const field = screen.getByLabelText("Adres").closest("[data-invalid]");
  await waitFor(() => expect(field?.getAttribute("data-invalid")).toBe("true"));
});

test("a type's settings change its name, kind and feed, in English too", async () => {
  const onLoaded = vi.fn();
  const rendered = renderIn(
    <ContentTypeSettings
      address="https://studio.example.test"
      onLoaded={onLoaded}
      onSwitchedOff={vi.fn()}
      siteId={siteId}
      typeId={projects.id}
    />,
    "en",
  );

  const name = (await screen.findByLabelText("Name")) as HTMLInputElement;
  expect(name.value).toBe("Realizacje");
  expect(onLoaded).toHaveBeenCalledWith(projects);
  const kind = screen.getByLabelText(
    "What the entries are",
  ) as HTMLSelectElement;
  expect(kind.value).toBe("WebPage");
  expect(
    within(kind)
      .getAllByRole("option")
      .map((item) => item.textContent),
  ).toEqual(["Blog posts", "Plain pages"]);
  const save = screen.getByRole("button", { name: "Save" });
  expect(save).toHaveProperty("disabled", true);
  // The address of projects is not „the blog's address”.
  expect(screen.getByText("Address in every language")).not.toBeNull();
  expect(screen.queryByText(/blog's address/i)).toBeNull();

  fireEvent.change(name, { target: { value: "Our projects" } });
  fireEvent.click(
    screen.getByLabelText(/Show the entries in the site's RSS feed/),
  );
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  fireEvent.click(save);

  await waitFor(() =>
    expect(updateContentType).toHaveBeenCalledWith(projects.id, {
      name: "Our projects",
      schema_type: "WebPage",
      in_site_feed: true,
    }),
  );
  expect(
    await screen.findByText("Content type settings saved."),
  ).not.toBeNull();
});

test("a switched-off type's settings say where to switch it on", async () => {
  renderIn(
    <ContentTypeSettings
      onSwitchedOff={vi.fn()}
      siteId={siteId}
      typeId={news.id}
    />,
  );

  expect(
    await screen.findByText(/Ten typ treści jest wyłączony/),
  ).not.toBeNull();
  expect(screen.queryByLabelText("Nazwa")).toBeNull();
  expect(
    screen.getByRole("link", { name: "Wszystkie typy treści" }),
  ).not.toBeNull();
});

test("the plan's refusal of a new type is about the type, not about its address", async () => {
  createContentCollection.mockRejectedValue(
    problem("quota_exceeded", [
      { field: null, code: "quota_exceeded", message: "Odmowa po polsku." },
    ]),
  );
  renderIn(<CreateContentTypeDialog onCreated={vi.fn()} siteId={siteId} />);
  fireEvent.click(screen.getByRole("button", { name: "Nowy typ treści" }));
  fireEvent.change(await screen.findByLabelText("Nazwa"), {
    target: { value: "Realizacje" },
  });
  await waitFor(() =>
    expect((screen.getByLabelText("Adres") as HTMLInputElement).value).toBe(
      "realizacje",
    ),
  );
  // Somebody else took the last place in the plan meanwhile.
  listContentTypes.mockResolvedValue(
    found({ allowed: false, code: "quota_exceeded", additional_max: 1 }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Dodaj typ treści" }));

  expect(
    await screen.findByText(/Twój plan nie obejmuje kolejnego typu treści/),
  ).not.toBeNull();
  expect(screen.queryByText("Odmowa po polsku.")).toBeNull();
  expect(screen.queryByLabelText("Adres")).toBeNull();
});
