/** `core.table` rows ⇄ the grid editor's document (ProseMirror JSON). The
 *  stored JSON is the source of truth, as with rich text (ADR-056): the
 *  editor is loaded from it and writes it back whole.
 *
 *  The document is one table of rows of cells; a cell is one run of text with
 *  rich text's marks. What the contract cannot hold the schema cannot hold
 *  either: no merged cells, no paragraphs or lists inside a cell. The grid is
 *  always a rectangle — a stored row shorter than the widest one is loaded
 *  with empty cells, and `tableGuard` refuses any edit that would change the
 *  shape except the editor's own row and column commands. */

import { Node, type AnyExtension, type JSONContent } from "@tiptap/core";
import { Bold } from "@tiptap/extension-bold";
import { Document } from "@tiptap/extension-document";
import { Italic } from "@tiptap/extension-italic";
import { Text } from "@tiptap/extension-text";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";

import type { TableV1Data } from "@saas-core/site-blocks";

import { spans, textNodes } from "./rich-text-doc";
import { RichLink } from "./rich-text-schema";

export type TableRows = TableV1Data["rows"];

/** The contract's limits (`core.table.v1.schema.json`). */
export const MAX_TABLE_ROWS = 120;
export const MAX_TABLE_COLUMNS = 12;

/** Set on the editor's own row and column commands and on a reload. */
export const TABLE_SHAPE = "tableShape";

/** What a new table section starts with: a header row and one row under it. */
export function emptyTableRows(): TableRows {
  return [{ cells: [{}, {}] }, { cells: [{}, {}] }];
}

const TableDocument = Document.extend({ content: "table" });

const Table = Node.create({
  name: "table",
  content: "tableRow+",
  isolating: true,
  parseHTML: () => [{ tag: "table" }],
  renderHTML: () => ["table", ["tbody", 0]],
});

const TableRow = Node.create({
  name: "tableRow",
  content: "tableCell+",
  parseHTML: () => [{ tag: "tr" }],
  renderHTML: () => ["tr", 0],
});

const TableCell = Node.create({
  name: "tableCell",
  content: "text*",
  // Backspace at the start of a cell stays in the cell.
  isolating: true,
  parseHTML: () => [{ tag: "td" }, { tag: "th" }],
  renderHTML: () => ["td", 0],
});

/** Rows and their cell counts: what must not change by typing. */
function shape(doc: ProseMirrorNode): string {
  const rows: number[] = [];
  doc.firstChild?.forEach((row) => rows.push(row.childCount));
  return rows.join(",");
}

/** Typing, deleting across cells or a drop can never add, remove or join
 *  cells; undo and redo of the editor's own history may. */
const tableGuard = new Plugin({
  key: new PluginKey("tableGuard"),
  filterTransaction: (tr, state) =>
    !tr.docChanged ||
    Boolean(tr.getMeta(TABLE_SHAPE)) ||
    Boolean(tr.getMeta("history$")) ||
    shape(tr.doc) === shape(state.doc),
});

export function tableExtensions(): AnyExtension[] {
  return [
    TableDocument,
    Table,
    TableRow,
    TableCell.extend({ addProseMirrorPlugins: () => [tableGuard] }),
    Text,
    Bold,
    Italic,
    RichLink,
  ];
}

export function toTableDoc(rows: TableRows): JSONContent {
  const source = rows.length > 0 ? rows : emptyTableRows();
  const columns = Math.max(1, ...source.map((row) => row.cells.length));
  return {
    type: "doc",
    content: [
      {
        type: "table",
        content: source.map((row) => ({
          type: "tableRow",
          content: Array.from({ length: columns }, (_, column) => {
            const content = textNodes(row.cells[column]?.content ?? []);
            return {
              type: "tableCell",
              ...(content.length > 0 ? { content } : {}),
            };
          }),
        })),
      },
    ],
  };
}

/** An empty cell is stored as `{}`: it keeps its place in the row and is no
 *  text unit of a translation. */
export function fromTableDoc(doc: JSONContent): TableRows {
  return (doc.content?.[0]?.content ?? []).map((row) => ({
    cells: (row.content ?? []).map((cell) => {
      const content = spans(cell.content);
      return content.length > 0 ? { content } : {};
    }),
  }));
}
