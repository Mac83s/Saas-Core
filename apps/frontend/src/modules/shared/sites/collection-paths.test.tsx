import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type ContentCollection } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { CollectionPaths } from "./collection-paths";

const { previewCollectionPaths, setCollectionPaths } = vi.hoisted(() => ({
  previewCollectionPaths: vi.fn(),
  setCollectionPaths: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  previewCollectionPaths,
  setCollectionPaths,
}));

const collection: ContentCollection = {
  id: "019ff20d-a000-7000-8000-000000000020",
  site_id: "019ff20d-a000-7000-8000-000000000010",
  key: "blog",
  name: "Blog",
  kind: "blog",
  base_path: "blog",
  locale_paths: {},
  paths: { pl: "/blog/", en: "/en/blog/", de: "/de/blog/" },
  automation_policy: "manual",
  show_in_navigation: false,
  schema_type: "BlogPosting",
  in_site_feed: true,
  archived: false,
  archived_at: null,
};

const renamed: ContentCollection = {
  ...collection,
  base_path: "poradnik",
  locale_paths: { de: "ratgeber" },
  paths: { pl: "/poradnik/", en: "/en/poradnik/", de: "/de/ratgeber/" },
};

const onSaved = vi.fn();

function renderPaths(value: ContentCollection = collection) {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CollectionPaths
        address="https://studio.example.test"
        collection={value}
        onSaved={onSaved}
      />
    </NextIntlClientProvider>,
  );
}

function field(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("shows the address in each language and stays accessible", async () => {
  const rendered = renderPaths(renamed);

  expect(screen.getByText("studio.example.test/poradnik/")).not.toBeNull();
  expect(screen.getByText("studio.example.test/en/poradnik/")).not.toBeNull();
  expect(screen.getByText("studio.example.test/de/ratgeber/")).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  fireEvent.click(screen.getByRole("button", { name: "Zmień adresy" }));
  // A language without a name of its own shows the one it follows.
  expect(field("Adres bloga — Polski").value).toBe("poradnik");
  expect(field("Adres bloga — English").value).toBe("");
  expect(field("Adres bloga — English").placeholder).toBe("poradnik");
  expect(field("Adres bloga — Deutsch").value).toBe("ratgeber");
  // The language's part of the address stands by itself, never cut short.
  expect(screen.getByText("/de/")).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("asks which addresses move, and for a reason, before it saves", async () => {
  previewCollectionPaths.mockResolvedValue({
    collection: renamed,
    moved: [{ locale: "pl", from_path: "/blog/", to_path: "/poradnik/" }],
    changed: true,
  });
  setCollectionPaths.mockResolvedValue({
    collection: renamed,
    moved: [{ locale: "pl", from_path: "/blog/", to_path: "/poradnik/" }],
    changed: true,
  });
  renderPaths();

  fireEvent.click(screen.getByRole("button", { name: "Zmień adresy" }));
  fireEvent.change(field("Adres bloga — Polski"), {
    target: { value: "poradnik" },
  });
  fireEvent.change(field("Adres bloga — Deutsch"), {
    target: { value: "ratgeber" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adresy" }));

  // The preview named an address that answers today: nothing is saved yet.
  expect(
    await screen.findByText(
      "studio.example.test/blog/ → studio.example.test/poradnik/",
    ),
  ).not.toBeNull();
  expect(
    screen.getByText(
      "Ta zmiana przenosi adresy, które już działają. Podaj powód.",
    ),
  ).not.toBeNull();
  expect(setCollectionPaths).not.toHaveBeenCalled();
  expect(previewCollectionPaths).toHaveBeenCalledWith(collection.id, {
    base_path: "poradnik",
    locale_paths: { de: "ratgeber" },
    reason: "",
  });

  fireEvent.change(field("Powód zmiany adresu"), {
    target: { value: "Polska nazwa działu" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adresy" }));

  await waitFor(() => expect(setCollectionPaths).toHaveBeenCalledOnce());
  expect(setCollectionPaths).toHaveBeenCalledWith(collection.id, {
    base_path: "poradnik",
    locale_paths: { de: "ratgeber" },
    reason: "Polska nazwa działu",
  });
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(renamed));
  expect(screen.getByRole("button", { name: "Zmień adresy" })).not.toBeNull();
});

test("saves a name nobody reads yet without a reason", async () => {
  const german = {
    ...collection,
    locale_paths: { de: "ratgeber" },
    paths: { ...collection.paths, de: "/de/ratgeber/" },
  };
  previewCollectionPaths.mockResolvedValue({
    collection: german,
    moved: [],
    changed: true,
  });
  setCollectionPaths.mockResolvedValue({
    collection: german,
    moved: [],
    changed: true,
  });
  renderPaths();

  fireEvent.click(screen.getByRole("button", { name: "Zmień adresy" }));
  fireEvent.change(field("Adres bloga — Deutsch"), {
    target: { value: "ratgeber" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adresy" }));

  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(german));
});

test("says a refused name at its own field", async () => {
  previewCollectionPaths.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Żądanie nie może zostać obsłużone",
      status: 400,
      code: "invalid",
      detail: {},
      correlation_id: null,
      errors: [
        {
          field: "locale_paths.de",
          code: "section_path_taken",
          message: "Inny dział ma już adres /news/ w języku de.",
        },
      ],
    } as never),
  );
  renderPaths();

  fireEvent.click(screen.getByRole("button", { name: "Zmień adresy" }));
  fireEvent.change(field("Adres bloga — Deutsch"), {
    target: { value: "news" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adresy" }));

  expect(
    await screen.findByText("Ten adres ma już inna część strony w tym języku."),
  ).not.toBeNull();
  expect(field("Adres bloga — Deutsch").getAttribute("aria-invalid")).toBe(
    "true",
  );
  expect(setCollectionPaths).not.toHaveBeenCalled();

  // A name that is not an address never reaches the server.
  previewCollectionPaths.mockClear();
  fireEvent.change(field("Adres bloga — Deutsch"), {
    target: { value: "Ratgeber für Hunde" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz adresy" }));
  expect(
    await screen.findByText("Użyj małych liter, cyfr i łączników."),
  ).not.toBeNull();
  expect(previewCollectionPaths).not.toHaveBeenCalled();
});
