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

import type { ContentEntry, EntryRemoval } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { RemoveEntryDialog } from "./remove-entry-dialog";

const { getPublicLocales, previewEntryRemoval, removeContentEntry } =
  vi.hoisted(() => ({
    getPublicLocales: vi.fn(),
    previewEntryRemoval: vi.fn(),
    removeContentEntry: vi.fn(),
  }));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getPublicLocales,
  previewEntryRemoval,
  removeContentEntry,
}));

const entry = {
  id: "019ff20d-a000-7000-8000-000000000030",
  title: "Jak dbać o włosy",
} as ContentEntry;

const removal = (extra: Partial<EntryRemoval> = {}): EntryRemoval => ({
  entry_id: entry.id,
  title: "Jak dbać o włosy",
  locale: "pl",
  removed: false,
  published: false,
  path: null,
  scheduled: false,
  machine_translation: false,
  other_languages: [],
  ...extra,
});

function renderDialog(
  onRemoved = vi.fn(),
  onClose = vi.fn(),
  locale: "pl" | "en" = "pl",
) {
  const rendered = render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <RemoveEntryDialog
        entry={entry}
        onClose={onClose}
        onRemoved={onRemoved}
      />
    </NextIntlClientProvider>,
  );
  return { rendered, onRemoved, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en", "de"],
    version: 1,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "en", native_name: "English", english_name: "English" },
      { code: "de", native_name: "Deutsch", english_name: "German" },
    ],
    limit: { allowed: true, additional_max: null, reason: "" },
    protected: {},
  });
  previewEntryRemoval.mockResolvedValue(removal());
  removeContentEntry.mockResolvedValue(removal({ removed: true }));
});

test("an entry that is not on the site says only that, and that it cannot be brought back", async () => {
  const { rendered } = renderDialog();
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText("Usunąć wpis „Jak dbać o włosy”?"),
  ).not.toBeNull();
  expect(previewEntryRemoval).toHaveBeenCalledWith(entry.id);
  expect(
    within(dialog).getByText(
      "Wpis nie jest na stronie. Zniknie z listy wpisów.",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText("Wpisu nie da się przywrócić w panelu."),
  ).not.toBeNull();
  // Each line only when it applies.
  expect(within(dialog).queryByText(/Zaplanowana publikacja/)).toBeNull();
  expect(within(dialog).queryByText(/Usuwasz tylko wersję/)).toBeNull();
  expect(within(dialog).queryByText(/powstało automatycznie/)).toBeNull();
  expect(within(dialog).queryByText(/przestanie odpowiadać/)).toBeNull();
  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);
});

test("a published, scheduled entry says what leaves the site and what is called off", async () => {
  previewEntryRemoval.mockResolvedValue(
    removal({ published: true, path: "/blog/jak-dbac/", scheduled: true }),
  );
  renderDialog();
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText(
      "Wpis zniknie ze strony od razu. Adres /blog/jak-dbac/ przestanie odpowiadać, a wpis wypadnie z list, kanału RSS i mapy strony.",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText("Zaplanowana publikacja zostanie odwołana."),
  ).not.toBeNull();
  expect(within(dialog).queryByText(/Wpis nie jest na stronie/)).toBeNull();
});

test("one language version says which one goes and which stay, and a machine translation says it may come back", async () => {
  previewEntryRemoval.mockResolvedValue(
    removal({
      locale: "en",
      machine_translation: true,
      other_languages: [
        { locale: "pl", title: "Jak dbać o włosy", state: "published" },
        { locale: "de", title: "Haarpflege", state: "draft" },
      ],
    }),
  );
  renderDialog();
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText(
      "Usuwasz tylko wersję w języku English. Pozostałe wersje językowe zostają: Polski, Deutsch.",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      "To tłumaczenie powstało automatycznie. Jeśli strona tłumaczy wpisy sama, może powstać ponownie przy kolejnym tłumaczeniu wpisu źródłowego. Żeby ta wersja nie wracała, wycofaj ją zamiast usuwać.",
    ),
  ).not.toBeNull();
});

test("removes after the preview and hands the entry back; cancelling removes nothing", async () => {
  const { onRemoved, onClose } = renderDialog();
  const dialog = await screen.findByRole("dialog");
  const confirm = within(dialog).getByRole("button", {
    name: "Usuń wpis",
  }) as HTMLButtonElement;
  // Not before the server has said what it does.
  await waitFor(() => expect(confirm.disabled).toBe(false));

  fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
  expect(onClose).toHaveBeenCalled();
  expect(removeContentEntry).not.toHaveBeenCalled();

  fireEvent.click(confirm);
  await waitFor(() =>
    expect(removeContentEntry).toHaveBeenCalledWith(entry.id),
  );
  await waitFor(() => expect(onRemoved).toHaveBeenCalledWith(entry));
});

test("speaks English", async () => {
  previewEntryRemoval.mockResolvedValue(
    removal({ published: true, path: "/en/blog/care/" }),
  );
  renderDialog(vi.fn(), vi.fn(), "en");
  const dialog = await screen.findByRole("dialog");

  expect(
    await within(dialog).findByText(
      "The entry leaves the site at once. The address /en/blog/care/ stops answering and the entry drops out of the lists, the RSS feed and the sitemap.",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByText(
      "The entry cannot be brought back from the panel.",
    ),
  ).not.toBeNull();
  expect(
    within(dialog).getByRole("button", { name: "Remove entry" }),
  ).not.toBeNull();
});
