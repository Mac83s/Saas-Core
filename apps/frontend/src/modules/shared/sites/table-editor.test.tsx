import axe from "axe-core";
import { Editor } from "@tiptap/core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { expect, test } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import {
  blockFormSchema,
  blockPayload,
  emptyBlock,
  registry,
  toSiteBlock,
} from "./block-form";
import {
  emptyTableRows,
  fromTableDoc,
  TABLE_SHAPE,
  tableExtensions,
  toTableDoc,
  type TableRows,
} from "./table-doc";
import { TableEditor } from "./table-editor";

// Typing, Tab between cells, links and undo run in a browser (contentEditable
// needs layout); jsdom checks what the grid loads, reloads, guards and offers.

const cell = (text: string) => ({ content: [{ text }] });
const rows: TableRows = [
  { cells: [cell("Usługa"), cell("Cena")] },
  {
    cells: [
      {
        content: [
          { text: "Kąpiel " },
          { text: "z suszeniem", bold: true, href: "/kapiel" },
        ],
      },
      {},
    ],
  },
];

test("rows go through the grid's document and come back as they were", () => {
  expect(fromTableDoc(toTableDoc(rows))).toEqual(rows);
  // A stored row shorter than the widest one is loaded as a full row.
  expect(
    fromTableDoc(
      toTableDoc([{ cells: [cell("a"), cell("b"), cell("c")] }, { cells: [] }]),
    ),
  ).toEqual([
    { cells: [cell("a"), cell("b"), cell("c")] },
    { cells: [{}, {}, {}] },
  ]);
  // Nothing stored: the grid a new table section starts with.
  expect(fromTableDoc(toTableDoc([]))).toEqual(emptyTableRows());
});

test("typing changes a cell; nothing typed or deleted changes the grid's shape", () => {
  const editor = new Editor({
    extensions: tableExtensions(),
    content: toTableDoc(rows),
  });
  // doc > table(1) > row(2) > cell(3): the first cell's text starts at 3.
  editor.view.dispatch(editor.state.tr.insertText("Nasza ", 3));
  expect(fromTableDoc(editor.getJSON())[0]!.cells[0]).toEqual(
    cell("Nasza Usługa"),
  );

  // A selection from the first cell into the second, deleted: the two
  // cells would join into one ("Nasza Usługa" ends at 15, "Cena" starts at 17).
  const before = editor.getJSON();
  editor.view.dispatch(editor.state.tr.delete(5, 18));
  expect(editor.getJSON()).toEqual(before);
  // A whole row removed by a stray edit is refused the same way…
  const row = editor.state.doc.firstChild!.child(0);
  editor.view.dispatch(editor.state.tr.delete(1, 1 + row.nodeSize));
  expect(editor.getJSON()).toEqual(before);
  // …and allowed when it is the editor's own command.
  editor.view.dispatch(
    editor.state.tr.delete(1, 1 + row.nodeSize).setMeta(TABLE_SHAPE, true),
  );
  expect(fromTableDoc(editor.getJSON())).toHaveLength(1);
  editor.destroy();
});

function Harness({
  children,
  value = rows,
}: {
  children: ReactNode;
  value?: TableRows;
}) {
  const form = useForm({
    defaultValues: { blocks: [{ data: { header: "row", rows: value } }] },
  });
  const stored = useWatch({
    control: form.control,
    name: "blocks.0.data.rows",
  });
  return (
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <FormProvider {...form}>
        {children}
        {/* What undo or a template does: replace the value. */}
        <button
          onClick={() =>
            form.setValue("blocks.0.data.rows", [
              { cells: [cell("Po cofnięciu")] },
            ])
          }
          type="button"
        >
          replace
        </button>
        <button
          onClick={() => form.setValue("blocks.0.data.header", "column")}
          type="button"
        >
          headers
        </button>
        <output aria-label="stored">{JSON.stringify(stored)}</output>
      </FormProvider>
    </NextIntlClientProvider>
  );
}

const editor = (
  <TableEditor
    headerName="blocks.0.data.header"
    label="Komórki tabeli"
    name="blocks.0.data.rows"
  />
);

const storedRows = () =>
  JSON.parse(screen.getByLabelText("stored").textContent ?? "[]") as TableRows;

test("the grid shows the stored cells with their marks, named and described", async () => {
  const { container } = render(<Harness>{editor}</Harness>);
  const grid = await screen.findByRole("textbox", { name: "Komórki tabeli" });
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(4));
  expect(grid.querySelectorAll("tr")).toHaveLength(2);
  expect(grid.querySelector("td a strong")?.textContent).toBe("z suszeniem");
  expect(grid.getAttribute("aria-describedby")).toBeTruthy();
  expect(
    document.getElementById(grid.getAttribute("aria-describedby")!)
      ?.textContent,
  ).toContain("Tab przechodzi do następnej komórki");
  // The cells the section's "Nagłówki" choice names look like headers.
  expect(
    container
      .querySelector(".table-editor__scroll")
      ?.getAttribute("data-header"),
  ).toBe("row");
  fireEvent.click(screen.getByRole("button", { name: "headers" }));
  await waitFor(() =>
    expect(
      container
        .querySelector(".table-editor__scroll")
        ?.getAttribute("data-header"),
    ).toBe("column"),
  );
  expect(screen.getByText("Wiersz 1 z 2, kolumna 1 z 2")).toHaveAttribute(
    "aria-live",
    "polite",
  );
  expect((await axe.run(container)).violations).toHaveLength(0);
});

test("rows and columns are added and removed with the buttons and written to the form", async () => {
  render(<Harness>{editor}</Harness>);
  const grid = await screen.findByRole("textbox", { name: "Komórki tabeli" });
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(4));
  const toolbar = within(
    screen.getByRole("toolbar", { name: "Formatowanie i układ tabeli" }),
  );

  fireEvent.click(toolbar.getByRole("button", { name: "Kolumna obok" }));
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(6));
  fireEvent.click(toolbar.getByRole("button", { name: "Wiersz poniżej" }));
  await waitFor(() => expect(grid.querySelectorAll("tr")).toHaveLength(3));
  // After a pause the whole grid is written; an empty cell is `{}` and
  // keeps its place in the row.
  await waitFor(
    () =>
      expect(storedRows()).toEqual([
        { cells: [cell("Usługa"), {}, cell("Cena")] },
        { cells: [{}, {}, {}] },
        { cells: [rows[1]!.cells[0], {}, {}] },
      ]),
    { timeout: 3000 },
  );

  fireEvent.click(toolbar.getByRole("button", { name: "Usuń wiersz" }));
  await waitFor(() => expect(grid.querySelectorAll("tr")).toHaveLength(2));
  fireEvent.click(toolbar.getByRole("button", { name: "Usuń kolumnę" }));
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(4));
});

test("the last row and the last column cannot be removed", async () => {
  render(<Harness value={[{ cells: [cell("jedyna")] }]}>{editor}</Harness>);
  const grid = await screen.findByRole("textbox", { name: "Komórki tabeli" });
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(1));
  // Disabled, and still reachable in the toolbar's arrow-key order.
  for (const name of ["Usuń wiersz", "Usuń kolumnę"])
    expect(screen.getByRole("button", { name })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
});

test("a value changed from outside reloads the grid", async () => {
  render(<Harness>{editor}</Harness>);
  const grid = await screen.findByRole("textbox", { name: "Komórki tabeli" });
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(4));
  fireEvent.click(screen.getByRole("button", { name: "replace" }));
  await waitFor(() => expect(grid.querySelectorAll("td")).toHaveLength(1));
  expect(grid.textContent).toBe("Po cofnięciu");
});

test("a new table section starts as a grid and saves its empty cells in place", () => {
  const fresh = emptyBlock("core.table");
  expect(fresh.data.rows).toEqual(emptyTableRows());
  expect(blockFormSchema.safeParse(fresh).success).toBe(true);
  const payload = blockPayload({
    block_type: "core.table",
    data: {
      caption: "  ",
      header: "row",
      rows: [{ cells: [{}, cell("Cena")] }, { cells: [cell("Kąpiel"), {}] }],
    },
  });
  // The blank caption goes; the empty cells stay where they are.
  expect(payload).toEqual({
    block_type: "core.table",
    schema_version: 1,
    data: {
      header: "row",
      rows: [{ cells: [{}, cell("Cena")] }, { cells: [cell("Kąpiel"), {}] }],
    },
  });
  expect(() => registry.validate(toSiteBlock(payload))).not.toThrow();
});

test("the published table passes axe with a caption, headers and a named scroll region", async () => {
  const { container } = render(
    <main>
      {registry.render(
        {
          block_type: "core.table",
          schema_version: 1,
          data: { caption: "Cennik", header: "both", rows },
        },
        "table",
      )}
    </main>,
  );
  expect(screen.getByRole("region", { name: "Cennik" })).toHaveAttribute(
    "tabindex",
    "0",
  );
  expect(screen.getByRole("table", { name: "Cennik" })).toBeInTheDocument();
  expect(screen.getAllByRole("columnheader")).toHaveLength(2);
  expect(screen.getAllByRole("rowheader")).toHaveLength(1);
  expect((await axe.run(container)).violations).toHaveLength(0);
});
