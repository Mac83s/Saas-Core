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
import {
  ApiProblemError,
  materializeTemplatePhoto,
} from "@saas-core/api-client";
import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { blockOption } from "./block-form";
import { SectionLibraryContent } from "./section-library";

// Core's library opens on all trades; a product may set its own
// (`siteIndustry`, section-library-industry.test.tsx). Pinned here so a
// product's slot does not change what these tests count.
vi.mock("../../../product", () => ({ product: {} }));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  materializeTemplatePhoto: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());

/** The library's category is a chip, named as the outline names that kind
 *  of section. */
function chooseCategory(type: string, locale: "pl" | "en" = "en") {
  const sites = (locale === "pl" ? pl : en).Sites;
  const name = sites[blockOption(type)!.labelKey as keyof typeof sites];
  fireEvent.click(
    within(
      screen.getByRole("group", { name: sites.sectionLibrary.category }),
    ).getByRole("button", { name: name as string }),
  );
}

test("a chip names a kind of section as the outline and the inspector do", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={pl}>
      <SectionLibraryContent compact onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  const names = within(screen.getByRole("group", { name: "Kategoria" }))
    .getAllByRole("button")
    .map((chip) => chip.textContent?.replace(/\d+$/, ""));
  expect(names).toEqual([
    "Wszystkie",
    "Baner powitalny",
    "Oferta",
    "Pytania i odpowiedzi",
    "Kontakt",
    "Formularz kontaktowy",
    "Social media i linki",
    "Separator",
    "Tekst",
    "Cytat",
    "Produkt",
    "Galeria",
  ]);
});

test.each(["pl", "en"] as const)(
  "copies a photo before inserting and reuses the retry key (%s)",
  async (locale) => {
    const onAdd = vi.fn();
    const onBusyChange = vi.fn();
    vi.mocked(materializeTemplatePhoto).mockRejectedValueOnce(
      new Error("Unavailable"),
    );
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent onAdd={onAdd} onBusyChange={onBusyChange} />
      </NextIntlClientProvider>,
    );
    const label =
      locale === "pl"
        ? "Dodaj: Klasyczne wprowadzenie"
        : "Add: Classic introduction";
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(onAdd).not.toHaveBeenCalled();
    vi.mocked(materializeTemplatePhoto).mockResolvedValueOnce({
      asset_id: "019ff20d-a000-7000-8000-000000000099",
    });
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(onAdd).toHaveBeenCalledOnce());
    const calls = vi.mocked(materializeTemplatePhoto).mock.calls;
    expect(calls[0]).toEqual(calls[1]);
    expect(onAdd.mock.calls[0][0].data.image.asset_id).toBe(
      "019ff20d-a000-7000-8000-000000000099",
    );
    expect(onAdd.mock.calls[0][0].data.image.alt).toContain(
      locale === "pl" ? "pracownia" : "studio",
    );
    expect(onBusyChange.mock.calls.at(-1)).toEqual([false]);
  },
);

test("a busy photo scanner says so, and the section can be added again", async () => {
  vi.mocked(materializeTemplatePhoto).mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Busy",
      status: 503,
      code: "media_scanner_unavailable",
      detail: "Server detail",
      correlation_id: null,
    }),
  );
  render(
    <NextIntlClientProvider locale="pl" messages={pl}>
      <SectionLibraryContent onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj: Klasyczne wprowadzenie" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    pl.Sites.sectionLibrary.scannerBusy,
  );
});

test("the category chips count what the search finds and hide the empty ones", () => {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent compact onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  const group = screen.getByRole("group", { name: "Category" });
  const chips = () => within(group).getAllByRole("button");
  expect(chips()).toHaveLength(12);
  expect(within(group).getByRole("button", { name: "All" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const search = screen.getByRole("searchbox", { name: "Find a template" });
  fireEvent.change(search, { target: { value: "captioned" } });
  expect(chips().length).toBeLessThan(12);
  const gallery = within(group).getByRole("button", { name: "Gallery" });
  const count = Number(gallery.textContent?.replace("Gallery", ""));
  expect(count).toBeGreaterThan(0);
  fireEvent.click(gallery);
  expect(gallery).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByRole("article")).toHaveLength(Math.min(count, 12));
  // The chosen category stays a chip when the search empties it.
  fireEvent.change(search, { target: { value: "missing layout" } });
  expect(
    within(group).getByRole("button", { name: "Gallery" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test("limits initial thumbnail rendering and exposes the remaining catalogue", () => {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.click(
    screen.getByRole("button", { name: "Show more templates (138 remaining)" }),
  );
  expect(screen.getAllByRole("article")).toHaveLength(24);
  chooseCategory("core.faq");
  expect(screen.getAllByRole("article")).toHaveLength(12);
  expect(
    screen.getByRole("button", { name: "Show more templates (8 remaining)" }),
  ).toBeDefined();
});

test.each(["pl", "en"] as const)(
  "searches the catalogue together with category and industry filters (%s)",
  (locale) => {
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent compact onAdd={vi.fn()} />
      </NextIntlClientProvider>,
    );
    fireEvent.change(
      screen.getByLabelText(locale === "pl" ? "Branża" : "Industry"),
      { target: { value: "medicine" } },
    );
    chooseCategory("core.feature_list", locale);
    const search = screen.getByRole("searchbox", {
      name: locale === "pl" ? "Szukaj szablonu" : "Find a template",
    });
    fireEvent.change(search, {
      target: {
        value: locale === "pl" ? "  KONSULTACJI  " : "  CONSULTATION  ",
      },
    });
    // With F4-P1 the practice's visit types mention the online consultation
    // (in English the word matches, in Polish its form does not).
    expect(screen.getAllByRole("article")).toHaveLength(
      locale === "pl" ? 2 : 3,
    );
    expect(
      screen.getByRole("button", {
        name:
          locale === "pl"
            ? "Dodaj: Ścieżka konsultacji"
            : "Add: Consultation pathway",
      }),
    ).toBeDefined();
    fireEvent.change(search, { target: { value: "missing layout" } });
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe(
      locale === "pl"
        ? "Brak sekcji spełniających wybrane filtry."
        : "No sections match the selected filters.",
    );
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getAllByRole("article")).toHaveLength(12);
  },
);

test.each(["pl", "en"] as const)(
  "opens an accessible full preview from the compact rail and restores focus (%s)",
  async (locale) => {
    const onAdd = vi.fn();
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent compact onAdd={onAdd} />
      </NextIntlClientProvider>,
    );
    // Ten families interleave, so the second FAQ layout is past the first page.
    chooseCategory("core.faq", locale);
    const trigger = screen.getByRole("button", {
      name:
        locale === "pl" ? "Podgląd: Rozwijane FAQ" : "Preview: Expandable FAQ",
    });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("region", {
        name: locale === "pl" ? "Podgląd sekcji" : "Section preview",
      }).textContent,
    ).toContain(locale === "pl" ? "Od czego zacząć?" : "How do I start?");
    const mobile = within(dialog).getByRole("button", {
      name: locale === "pl" ? "Widok telefonu" : "Phone view",
    });
    fireEvent.click(mobile);
    expect(mobile).toHaveAttribute("aria-pressed", "true");
    const result = await axe.run(dialog, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: locale === "pl" ? "Zamknij" : "Close",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: locale === "pl" ? "Dodaj: Rozwijane FAQ" : "Add: Expandable FAQ",
      }),
    );
    expect(onAdd).toHaveBeenCalledOnce();
    expect(onAdd.mock.calls[0][0].block_type).toBe("core.faq");
    expect(materializeTemplatePhoto).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  },
);

test("keeps photo preparation and a retry error visible in the preview", async () => {
  let rejectPhoto!: (error: Error) => void;
  vi.mocked(materializeTemplatePhoto).mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectPhoto = reject;
      }),
  );
  const onAdd = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent compact onAdd={onAdd} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Preview: Classic introduction" }),
  );
  const dialog = screen.getByRole("dialog");
  const add = within(dialog).getByRole("button", {
    name: "Add: Classic introduction",
  });
  fireEvent.click(add);
  expect(add).toBeDisabled();
  expect(within(dialog).getByRole("status")).toHaveTextContent(
    "Preparing the photo",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeDefined();
  rejectPhoto(new Error("Unavailable"));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Could not prepare the photo",
  );
  expect(add).not.toBeDisabled();
  expect(onAdd).not.toHaveBeenCalled();
});

test.each([
  ["core.contact", 6],
  ["core.contact_form", 4],
  ["core.link_list", 6],
  ["core.separator", 8],
  ["core.quote", 6],
] as const)(
  "offers all %s layouts and copies editable data",
  async (type, count) => {
    const onAdd = vi.fn();
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <SectionLibraryContent onAdd={onAdd} />
      </NextIntlClientProvider>,
    );
    chooseCategory(type);
    expect(screen.getAllByRole("article")).toHaveLength(count);
    const first = screen.getAllByRole("article")[0];
    fireEvent.click(within(first).getByRole("button", { name: /^Add: / }));
    await waitFor(() => expect(onAdd).toHaveBeenCalledOnce());
    expect(onAdd.mock.calls[0][0].block_type).toBe(type);
    if (type === "core.contact_form") {
      expect(onAdd.mock.calls[0][0].data.locale).toBe("en");
      expect(onAdd.mock.calls[0][0].data.submit_label).toBe("Send message");
      expect(document.querySelectorAll("form")).toHaveLength(0);
    }
  },
);

test("puts a product's sample photo into its gallery, not into `image`", async () => {
  vi.mocked(materializeTemplatePhoto).mockResolvedValueOnce({
    asset_id: "019ff20d-a000-7000-8000-000000000123",
  });
  const onAdd = vi.fn();
  render(
    <NextIntlClientProvider locale="pl" messages={pl}>
      <SectionLibraryContent onAdd={onAdd} />
    </NextIntlClientProvider>,
  );
  chooseCategory("core.product", "pl");
  // The showcase and seven product v3 layouts, and two electronics add-ons.
  expect(screen.getAllByRole("article")).toHaveLength(10);
  expect(screen.getAllByText(/Długość:/).length).toBeGreaterThan(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj: Prezentacja produktu" }),
  );
  await waitFor(() => expect(onAdd).toHaveBeenCalledOnce());
  const block = onAdd.mock.calls[0][0];
  expect(block.block_type).toBe("core.product");
  expect(block.data.image).toBeUndefined();
  expect(block.data.images[0].asset_id).toBe(
    "019ff20d-a000-7000-8000-000000000123",
  );
  expect(block.data.images[0].alt.length).toBeGreaterThan(0);
});

test("copies each sample photo of a gallery once and puts it on its own item", async () => {
  const assets: Record<string, string> = {
    business: "019ff20d-a000-7000-8000-000000000201",
    medicine: "019ff20d-a000-7000-8000-000000000202",
    agriculture: "019ff20d-a000-7000-8000-000000000203",
    electronics: "019ff20d-a000-7000-8000-000000000204",
  };
  vi.mocked(materializeTemplatePhoto).mockImplementation(async (photo) => ({
    asset_id: assets[photo],
  }));
  const onAdd = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent onAdd={onAdd} />
    </NextIntlClientProvider>,
  );
  chooseCategory("core.gallery");
  expect(screen.getAllByRole("article")).toHaveLength(6);
  fireEvent.click(screen.getByRole("button", { name: "Add: Captioned grid" }));
  await waitFor(() => expect(onAdd).toHaveBeenCalledOnce());
  const photos = vi
    .mocked(materializeTemplatePhoto)
    .mock.calls.map(([photo]) => photo);
  expect(photos).toEqual([
    "business",
    "medicine",
    "agriculture",
    "electronics",
  ]);
  const block = onAdd.mock.calls[0][0];
  expect(block.block_type).toBe("core.gallery");
  expect(
    block.data.items.map(
      (item: { image: { asset_id: string } }) => item.image.asset_id,
    ),
  ).toEqual(photos.map((photo) => assets[photo]));
});

test("offers all twenty editorial layouts, the first twelve before 'show more'", () => {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  chooseCategory("core.rich_text");
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.click(
    screen.getByRole("button", { name: "Show more templates (8 remaining)" }),
  );
  expect(screen.getAllByRole("article")).toHaveLength(20);
});
