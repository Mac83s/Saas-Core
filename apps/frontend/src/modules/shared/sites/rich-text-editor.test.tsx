import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { expect, test } from "vitest";

import type { RichTextNode } from "@saas-core/site-blocks";

import polishMessages from "../../../../messages/pl.json";
import { RichTextEditor } from "./rich-text-editor";

// Typing, shortcuts, links and undo run in a browser (contentEditable needs
// layout); jsdom checks what the editor loads, reloads and offers.

const content: RichTextNode[] = [
  {
    type: "paragraph",
    content: [{ text: "Najpierw " }, { text: "rozmowa", bold: true }],
  },
  { type: "heading", level: 2, anchor: "plan", text: "Plan pracy" },
  {
    type: "list",
    style: "bullet",
    items: [
      {
        content: [{ text: "punkt" }],
        children: {
          style: "ordered",
          items: [{ content: [{ text: "podpunkt" }] }],
        },
      },
    ],
  },
];

function Harness({
  children,
  value = content,
}: {
  children: ReactNode;
  value?: RichTextNode[];
}) {
  const form = useForm({
    defaultValues: { blocks: [{ data: { content: value } }] },
  });
  return (
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <FormProvider {...form}>
        {children}
        {/* What undo, the canvas or a template does: replace the value. */}
        <button
          onClick={() =>
            form.setValue("blocks.0.data.content", [
              { type: "paragraph", content: [{ text: "Po cofnięciu" }] },
            ])
          }
          type="button"
        >
          replace
        </button>
        <output aria-label="form">
          {form.formState.isDirty ? "dirty" : "clean"}
        </output>
      </FormProvider>
    </NextIntlClientProvider>
  );
}

test("loads the stored text as a document and reloads it when the value changes elsewhere", async () => {
  render(
    <Harness>
      <RichTextEditor label="Treść sekcji" name="blocks.0.data.content" />
    </Harness>,
  );
  const text = await screen.findByRole("textbox", { name: "Treść sekcji" });
  await waitFor(() =>
    expect(text.querySelector("h2")?.textContent).toContain("Plan pracy"),
  );
  expect(text.querySelector("strong")?.textContent).toBe("rozmowa");
  expect(text.querySelector("ul ol li")?.textContent).toBe("podpunkt");
  // The heading's anchor shows where a link to it points; it is not text.
  expect(text.querySelector(".rich-text-editor__anchor")?.textContent).toBe(
    "#plan",
  );
  expect(screen.getByRole("toolbar", { name: "Formatowanie" })).not.toBeNull();
  expect(screen.getByLabelText("Styl akapitu")).not.toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "replace" }));
  await waitFor(() => expect(text.textContent).toBe("Po cofnięciu"));
  // Reloading is not an edit: nothing is written back.
  expect(screen.getByRole("status", { name: "form" }).textContent).toBe(
    "clean",
  );

  const results = await axe.run(document.body, {
    rules: { region: { enabled: false } },
  });
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
});

test("the aside offers only paragraphs and lists", async () => {
  render(
    <Harness value={[content[0]!, content[2]!]}>
      <RichTextEditor
        allowedNodes={["paragraph", "list"]}
        label="Ramka boczna"
        name="blocks.0.data.content"
      />
    </Harness>,
  );
  await screen.findByRole("textbox", { name: "Ramka boczna" });
  expect(screen.queryByLabelText("Styl akapitu")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Lista punktowana" }),
  ).not.toBeNull();
});

test("quotes, notes and figures are cards with their fields", async () => {
  render(
    <Harness
      value={[
        {
          type: "quote",
          content: [{ text: "Dobre biuro to spokój." }],
          author: "Anna",
        },
        { type: "note", tone: "tip", content: [{ text: "Zabierz rzut." }] },
        {
          type: "figure",
          image: {
            asset_id: "00000000-0000-4000-8000-000000000001",
            alt: "Biuro",
          },
          width: "wide",
        },
        {
          type: "paragraph",
          content: [{ text: "Cena: [Uzupełnij: kwota] za metr." }],
        },
      ]}
    >
      <RichTextEditor label="Treść sekcji" name="blocks.0.data.content" />
    </Harness>,
  );
  const text = await screen.findByRole("textbox", { name: "Treść sekcji" });
  expect(await within(text).findByDisplayValue("Anna")).not.toBeNull();
  expect(within(text).getByLabelText("Rodzaj uwagi")).toHaveProperty(
    "value",
    "tip",
  );
  expect(within(text).getByLabelText("Szerokość ilustracji")).toHaveProperty(
    "value",
    "wide",
  );
  expect(
    within(text).getByRole("button", { name: "Usuń element: Cytat" }),
  ).not.toBeNull();
  // The place to fill in is marked and counted.
  expect(text.querySelector(".rich-text-editor__todo")?.textContent).toBe(
    "[Uzupełnij: kwota]",
  );
  expect(screen.getByText("Zostało 1 miejsce do uzupełnienia.")).not.toBeNull();
});

test("full screen moves the same editor into a dialog and back", async () => {
  render(
    <Harness>
      <RichTextEditor label="Treść sekcji" name="blocks.0.data.content" />
    </Harness>,
  );
  await screen.findByRole("textbox", { name: "Treść sekcji" });
  fireEvent.click(
    screen.getByRole("button", { name: "Pisz na pełnym ekranie" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Treść sekcji" });
  // One editor, now in the dialog; the panel only says where it went.
  expect(
    within(dialog).getByRole("textbox", { name: "Treść sekcji" }),
  ).toHaveTextContent("Plan pracy");
  expect(screen.getAllByRole("textbox", { name: "Treść sekcji" })).toHaveLength(
    1,
  );
  expect(
    screen.getByText("Tekst jest otwarty na pełnym ekranie."),
  ).not.toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Gotowe" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    screen.getByRole("textbox", { name: "Treść sekcji" }),
  ).toHaveTextContent("Plan pracy");
});
