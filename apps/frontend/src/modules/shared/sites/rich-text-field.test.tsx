import axe from "axe-core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import {
  FormProvider,
  useForm,
  type FieldValues,
  type UseFormReturn,
} from "react-hook-form";
import { afterEach, expect, test, vi } from "vitest";

import type { RichTextNode } from "@saas-core/site-blocks";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { useDraftHistory } from "./draft-history";
import { RichTextField } from "./rich-text-field";

afterEach(cleanup);

const NAME = "blocks.1.data.content";
const ASSET = "0b8d1f5e-3c2a-4e7b-9a61-2f4c8d9e1a73";

function initialBlocks(content: RichTextNode[]) {
  return [
    {
      block_type: "core.rich_text",
      data: {
        content: [
          { type: "heading", level: 2, anchor: "oferta", text: "Oferta" },
        ],
      },
    },
    { block_type: "core.rich_text", data: { content } },
  ];
}

const DEFAULT_CONTENT: RichTextNode[] = [
  {
    type: "paragraph",
    content: [{ text: "Wstęp " }, { text: "ważny", bold: true }],
  },
  { type: "heading", level: 2, anchor: "cennik", text: "Cennik" },
];

function renderField({
  locale = "pl",
  content = DEFAULT_CONTENT,
  allowedNodes,
}: {
  locale?: "pl" | "en";
  content?: RichTextNode[];
  allowedNodes?: ("paragraph" | "list")[];
} = {}) {
  const handle: { form?: UseFormReturn<FieldValues> } = {};
  function Harness() {
    const form = useForm<FieldValues>({
      defaultValues: { blocks: initialBlocks(content) },
    });
    const history = useDraftHistory(form);
    handle.form = form;
    return (
      <FormProvider {...form}>
        <form aria-label="Szkic">
          <RichTextField
            allowedNodes={allowedNodes}
            label={locale === "pl" ? "Treść sekcji" : "Section text"}
            mediaOptions={[{ id: ASSET, label: "gabinet.jpg" }]}
            name={NAME}
          />
          <button
            disabled={!history.canUndo}
            onClick={history.undo}
            type="button"
          >
            Cofnij
          </button>
        </form>
      </FormProvider>
    );
  }
  const view = render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <Harness />
    </NextIntlClientProvider>,
  );
  const nodes = () => handle.form!.getValues(NAME) as RichTextNode[];
  return { ...view, form: () => handle.form!, nodes };
}

function paste(target: HTMLElement, data: Record<string, string>) {
  fireEvent.paste(target, {
    clipboardData: { getData: (type: string) => data[type] ?? "" },
  });
}

test.each(["pl", "en"] as const)(
  "panel %s ma etykiety, spis śródtytułów i przechodzi axe",
  async (locale) => {
    const { container } = renderField({ locale });
    const pl = locale === "pl";
    expect(
      screen.getByRole("group", { name: pl ? "Treść sekcji" : "Section text" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("textbox", {
        name: pl ? "Treść akapitu" : "Paragraph text",
      }),
    ).toHaveValue("Wstęp **ważny**");
    expect(
      screen.getByRole("textbox", {
        name: pl ? "Tekst śródtytułu" : "Heading text",
      }),
    ).toHaveValue("Cennik");
    const outline = screen.getByRole("navigation", {
      name: pl ? "Spis śródtytułów" : "Headings outline",
    });
    expect(
      within(outline).getByRole("button", { name: "Cennik" }),
    ).not.toBeNull();
    expect(
      screen.getAllByRole("button", {
        name: pl ? "Przesuń element niżej" : "Move element down",
      }),
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", {
        name: pl ? "Pogrubienie (Ctrl+B)" : "Bold (Ctrl+B)",
      }),
    ).toHaveAttribute("aria-keyshortcuts", "Control+B Meta+B");
    expect((await axe.run(container)).violations).toHaveLength(0);
  },
);

test("wstawia każdy rodzaj elementu po bieżącym, z nową kotwicą i fokusem", async () => {
  const { container, nodes } = renderField();
  const insert = within(
    screen.getByRole("group", { name: "Wstaw po bieżącym elemencie" }),
  );
  fireEvent.focus(screen.getByRole("textbox", { name: "Treść akapitu" }));
  for (const name of [
    "Akapit",
    "Śródtytuł H2",
    "Śródtytuł H3",
    "Śródtytuł H4",
    "Lista punktowana",
    "Lista numerowana",
    "Cytat",
    "Uwaga",
    "Ilustracja",
  ])
    fireEvent.click(insert.getByRole("button", { name }));
  expect(nodes()).toEqual([
    DEFAULT_CONTENT[0],
    { type: "paragraph", content: [] },
    { type: "heading", level: 2, anchor: "section", text: "" },
    { type: "heading", level: 3, anchor: "section-2", text: "" },
    { type: "heading", level: 4, anchor: "section-3", text: "" },
    { type: "list", style: "bullet", items: [] },
    { type: "list", style: "ordered", items: [] },
    { type: "quote", content: [], author: "", source: "", href: "" },
    { type: "note", tone: "info", title: "", content: [] },
    {
      type: "figure",
      image: { asset_id: "", alt: "" },
      caption: "",
      width: "column",
    },
    DEFAULT_CONTENT[1],
  ]);
  expect(document.activeElement).toBe(
    screen.getByRole("combobox", { name: "Obraz" }),
  );
  expect(screen.getByRole("group", { name: "10. Ilustracja" })).not.toBeNull();
  expect((await axe.run(container)).violations).toHaveLength(0);
});

test("pierwszy tekst śródtytułu nadaje kotwicę unikalną w całym formularzu i już jej nie zmienia", () => {
  const { nodes } = renderField({ content: [] });
  expect(
    screen.getByText("Tekst jest pusty. Wstaw pierwszy element."),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Śródtytuł H2" }));
  const text = screen.getByRole("textbox", { name: "Tekst śródtytułu" });
  expect(document.activeElement).toBe(text);
  fireEvent.change(text, { target: { value: "Oferta" } });
  fireEvent.blur(text);
  // "oferta" is taken by the first block.
  expect(nodes()[0]).toMatchObject({ anchor: "oferta-2", text: "Oferta" });
  fireEvent.change(text, { target: { value: "Oferta specjalna" } });
  fireEvent.blur(text);
  expect(nodes()[0]).toMatchObject({
    anchor: "oferta-2",
    text: "Oferta specjalna",
  });
  const anchor = screen.getByRole("textbox", { name: "Kotwica" });
  expect(anchor).toHaveAccessibleDescription(/#oferta-2/);
  fireEvent.change(anchor, { target: { value: "oferta" } });
  expect(anchor).toHaveAttribute("aria-invalid", "true");
  expect(
    screen.getByText("Ta kotwica jest już użyta na tej stronie."),
  ).not.toBeNull();
  fireEvent.change(anchor, { target: { value: "Zła kotwica" } });
  expect(screen.getByText(/Kotwica zaczyna się literą/)).not.toBeNull();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Poziom śródtytułu" }),
    {
      target: { value: "3" },
    },
  );
  expect(nodes()[0]).toMatchObject({ level: 3 });
});

test("przesuwa, usuwa i przenosi fokus ze spisu do śródtytułu", () => {
  const { nodes } = renderField();
  fireEvent.click(
    within(screen.getByRole("group", { name: "1. Akapit" })).getByRole(
      "button",
      {
        name: "Przesuń element niżej",
      },
    ),
  );
  expect(nodes().map((node) => node.type)).toEqual(["heading", "paragraph"]);
  expect(
    within(screen.getByRole("group", { name: "1. Śródtytuł" })).getByRole(
      "button",
      {
        name: "Przesuń element wyżej",
      },
    ),
  ).toBeDisabled();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Spis śródtytułów" }),
    ).getByRole("button", { name: "Cennik" }),
  );
  expect(document.activeElement).toBe(
    screen.getByRole("textbox", { name: "Tekst śródtytułu" }),
  );
  fireEvent.click(
    within(screen.getByRole("group", { name: "1. Śródtytuł" })).getByRole(
      "button",
      {
        name: "Usuń element",
      },
    ),
  );
  expect(nodes()).toEqual([DEFAULT_CONTENT[0]]);
  expect(screen.getByRole("status")).toHaveTextContent("Usunięto element.");
  expect(
    screen.queryByRole("navigation", { name: "Spis śródtytułów" }),
  ).toBeNull();
});

test("pogrubia i pochyla zaznaczenie przyciskiem i skrótem, a pisanie zapisuje dopiero po zatrzymaniu", () => {
  const { nodes } = renderField();
  const area = screen.getByRole("textbox", {
    name: "Treść akapitu",
  }) as HTMLTextAreaElement;
  area.setSelectionRange(0, 5);
  fireEvent.click(screen.getByRole("button", { name: "Pogrubienie (Ctrl+B)" }));
  expect(area).toHaveValue("**Wstęp** **ważny**");
  expect([area.selectionStart, area.selectionEnd]).toEqual([2, 7]);
  expect(nodes()[0]).toEqual({
    type: "paragraph",
    content: [
      { text: "Wstęp", bold: true },
      { text: " " },
      { text: "ważny", bold: true },
    ],
  });
  fireEvent.keyDown(area, { key: "i", ctrlKey: true });
  expect(area).toHaveValue("***Wstęp*** **ważny**");
  fireEvent.keyDown(area, { key: "B", metaKey: true });
  expect(area).toHaveValue("*Wstęp* **ważny**");
  expect(nodes()[0]).toMatchObject({
    content: [
      { text: "Wstęp", italic: true },
      { text: " " },
      { text: "ważny", bold: true },
    ],
  });

  fireEvent.change(area, { target: { value: "Nowy *tekst*  z odstępem " } });
  // The buffer keeps what was typed; the form still has the last commit.
  expect(area).toHaveValue("Nowy *tekst*  z odstępem ");
  expect(nodes()[0]).toMatchObject({
    content: [
      { text: "Wstęp", italic: true },
      { text: " " },
      { text: "ważny", bold: true },
    ],
  });
  fireEvent.blur(area);
  expect(nodes()[0]).toEqual({
    type: "paragraph",
    content: [
      { text: "Nowy " },
      { text: "tekst", italic: true },
      { text: "  z odstępem " },
    ],
  });
});

test("link: sprawdza adres wzorcem kontraktu i opakowuje zaznaczenie", () => {
  const { nodes } = renderField();
  const area = screen.getByRole("textbox", {
    name: "Treść akapitu",
  }) as HTMLTextAreaElement;
  area.setSelectionRange(0, 5);
  fireEvent.click(screen.getByRole("button", { name: "Link" }));
  const url = screen.getByRole("textbox", { name: "Adres linku" });
  expect(document.activeElement).toBe(url);
  fireEvent.change(url, { target: { value: "javascript:alert(1)" } });
  fireEvent.keyDown(url, { key: "Enter" });
  expect(url).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText(/Ten adres nie jest dozwolony/)).not.toBeNull();
  fireEvent.change(url, { target: { value: "/kontakt" } });
  fireEvent.click(screen.getByRole("button", { name: "Wstaw link" }));
  expect(area).toHaveValue("[Wstęp](/kontakt) **ważny**");
  expect(nodes()[0]).toMatchObject({
    content: [
      { text: "Wstęp", href: "/kontakt" },
      { text: " " },
      { text: "ważny", bold: true },
    ],
  });
  expect(screen.queryByRole("textbox", { name: "Adres linku" })).toBeNull();
});

test("wklejenie HTML z dokumentu wstawia węzły jako jeden krok historii i mówi o pominiętych obrazach", () => {
  const { nodes } = renderField();
  const area = screen.getByRole("textbox", { name: "Treść akapitu" });
  paste(area, {
    "text/html":
      '<b style="font-weight:normal" id="docs-internal-guid-x"><h2>Cennik</h2><p><span style="font-weight:700">Od</span> 100 zł</p><img src="a.png"><ul><li>jeden</li></ul></b>',
    "text/plain": "Cennik\n\nOd 100 zł\n\njeden",
  });
  expect(nodes()).toEqual([
    DEFAULT_CONTENT[0],
    // "cennik" is already used further down this text.
    { type: "heading", level: 2, anchor: "cennik-2", text: "Cennik" },
    {
      type: "paragraph",
      content: [{ text: "Od", bold: true }, { text: " 100 zł" }],
    },
    {
      type: "list",
      style: "bullet",
      items: [{ content: [{ text: "jeden" }] }],
    },
    DEFAULT_CONTENT[1],
  ]);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Wklejono 3 elementy. Obrazy ze schowka nie zostały zaimportowane",
  );
  expect(document.activeElement).toBe(
    screen.getByRole("textbox", { name: "Pozycje listy" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(nodes()).toEqual(DEFAULT_CONTENT);
  expect(screen.getByRole("button", { name: "Cofnij" })).toBeDisabled();
});

test("zwykły tekst z pustymi liniami zastępuje pusty akapit, a jeden wiersz wkleja się dosłownie", () => {
  const { nodes } = renderField({
    content: [{ type: "paragraph", content: [] }],
  });
  const area = screen.getByRole("textbox", {
    name: "Treść akapitu",
  }) as HTMLTextAreaElement;
  paste(area, { "text/plain": "2*3 = 6" });
  expect(area).toHaveValue("2\\*3 = 6");
  expect(nodes()).toEqual([
    { type: "paragraph", content: [{ text: "2*3 = 6" }] },
  ]);
  fireEvent.change(area, { target: { value: "" } });
  fireEvent.blur(area);
  paste(screen.getByRole("textbox", { name: "Treść akapitu" }), {
    "text/plain": "Pierwszy\n\nDrugi\n- punkt",
  });
  expect(nodes()).toEqual([
    { type: "paragraph", content: [{ text: "Pierwszy" }] },
    { type: "paragraph", content: [{ text: "Drugi" }] },
    {
      type: "list",
      style: "bullet",
      items: [{ content: [{ text: "punkt" }] }],
    },
  ]);
});

test("dzieli akapit przeniesiony z v1 po pustych liniach", () => {
  const { nodes } = renderField({
    content: [{ type: "paragraph", content: [{ text: "Pierwszy\n\nDrugi" }] }],
  });
  fireEvent.click(screen.getByRole("button", { name: "Podziel na akapity" }));
  expect(nodes()).toEqual([
    { type: "paragraph", content: [{ text: "Pierwszy" }] },
    { type: "paragraph", content: [{ text: "Drugi" }] },
  ]);
  expect(
    screen.queryByRole("button", { name: "Podziel na akapity" }),
  ).toBeNull();
});

test("lista: jedno pole, wcięcie tworzy podpozycje", () => {
  const { nodes } = renderField({
    content: [
      { type: "list", style: "bullet", items: [{ content: [{ text: "a" }] }] },
    ],
  });
  const area = screen.getByRole("textbox", { name: "Pozycje listy" });
  expect(area).toHaveValue("a");
  fireEvent.change(area, { target: { value: "a\n  1. b\n**c**" } });
  fireEvent.blur(area);
  expect(nodes()[0]).toEqual({
    type: "list",
    style: "bullet",
    items: [
      {
        content: [{ text: "a" }],
        children: { style: "ordered", items: [{ content: [{ text: "b" }] }] },
      },
      { content: [{ text: "c", bold: true }] },
    ],
  });
});

test("ilustracja: wybór obrazu i błąd tekstu alternatywnego z formularza", () => {
  const { form, nodes } = renderField({
    content: [
      { type: "figure", image: { asset_id: "", alt: "" }, width: "column" },
    ],
  });
  const alt = screen.getByRole("textbox", { name: "Tekst alternatywny" });
  expect(alt).toHaveAttribute("aria-required", "false");
  fireEvent.change(screen.getByRole("combobox", { name: "Obraz" }), {
    target: { value: ASSET },
  });
  expect(nodes()[0]).toMatchObject({ image: { asset_id: ASSET, alt: "" } });
  expect(alt).toHaveAttribute("aria-required", "true");
  act(() =>
    form().setError(`${NAME}.0.image.alt`, {
      type: "custom",
      message: "required",
    }),
  );
  expect(alt).toHaveAttribute("aria-invalid", "true");
  expect(alt).toHaveAccessibleDescription(/To pole jest wymagane\./);
  expect(screen.getByRole("group", { name: "1. Ilustracja" })).toHaveAttribute(
    "data-invalid",
    "true",
  );
});

test("błąd przebiegów pod akapitem trafia do jego pola", () => {
  const { form } = renderField();
  act(() =>
    form().setError(`${NAME}.0.content.1.text`, {
      type: "custom",
      message: "tooLong",
    }),
  );
  expect(
    screen.getByRole("textbox", { name: "Treść akapitu" }),
  ).toHaveAccessibleDescription(/Tekst jest za długi dla tego bloku\./);
});

test("panel faktów dopuszcza tylko akapity i listy", () => {
  renderField({ allowedNodes: ["paragraph", "list"], locale: "en" });
  expect(
    within(
      screen.getByRole("group", { name: "Insert after the current element" }),
    )
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Paragraph", "Bulleted list", "Numbered list"]);
});

test("opcjonalne pola nie przejmują wartości domyślnych innego węzła po przesunięciu i cofnięciu", () => {
  const { nodes } = renderField({
    content: [
      { type: "quote", content: [{ text: "A" }], author: "Jan" },
      { type: "quote", content: [{ text: "B" }] },
    ],
  });
  fireEvent.click(
    within(screen.getByRole("group", { name: "2. Cytat" })).getByRole(
      "button",
      { name: "Przesuń element wyżej" },
    ),
  );
  const authors = () => screen.getAllByRole("textbox", { name: "Autor" });
  fireEvent.change(authors()[1], { target: { value: "Janina" } });
  fireEvent.blur(authors()[1]);
  expect(nodes()[1]).toMatchObject({ author: "Janina" });
  fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
  expect(nodes()).toEqual([
    { type: "quote", content: [{ text: "B" }] },
    { type: "quote", content: [{ text: "A" }], author: "Jan" },
  ]);
  expect(authors().map((input) => (input as HTMLInputElement).value)).toEqual([
    "",
    "Jan",
  ]);
});

test("pisanie zapisuje przebiegi po krótkiej przerwie jako jeden krok", () => {
  vi.useFakeTimers();
  try {
    const { nodes } = renderField();
    const area = screen.getByRole("textbox", { name: "Treść akapitu" });
    fireEvent.change(area, { target: { value: "Wstęp **ważny** i" } });
    fireEvent.change(area, { target: { value: "Wstęp **ważny** i *dalej*" } });
    expect(nodes()).toEqual(DEFAULT_CONTENT);
    act(() => vi.advanceTimersByTime(800));
    expect(nodes()[0]).toEqual({
      type: "paragraph",
      content: [
        { text: "Wstęp " },
        { text: "ważny", bold: true },
        { text: " i " },
        { text: "dalej", italic: true },
      ],
    });
    expect(area).toHaveValue("Wstęp **ważny** i *dalej*");
    fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
    expect(nodes()).toEqual(DEFAULT_CONTENT);
    // Undo resets the form, so the field is a new element.
    expect(screen.getByRole("textbox", { name: "Treść akapitu" })).toHaveValue(
      "Wstęp **ważny**",
    );
  } finally {
    vi.useRealTimers();
  }
});
