import { createElement as h, type ReactElement } from "react";

import { plainBlockText } from "./block-text";
import { renderInlineRun } from "./rich-text-block";
import { siteUiTexts } from "./site-ui-texts";
import type { BlockComponentProps, TableCell, TableV1Data } from "./types";

/** As many columns as the longest row: a shorter row is filled with empty
 *  cells, so the grid stays a rectangle whatever was stored. */
export function tableColumnCount(rows: TableV1Data["rows"]): number {
  return rows.reduce((most, row) => Math.max(most, row.cells.length), 0);
}

/**
 * A data table (`core.table`). Real table markup: a caption, header cells
 * with their scope, no merged cells. A table wider than its place scrolls
 * sideways inside a region a keyboard reaches and a screen reader hears by
 * the caption — the page itself never scrolls sideways on a phone.
 */
export function TableBlock({
  data,
  editor,
  options,
}: BlockComponentProps): ReactElement {
  const text = editor?.text ?? plainBlockText;
  const table = data as TableV1Data;
  const layout = table.layout ?? "lines";
  const header = table.header ?? "row";
  const headerRow = header === "row" || header === "both";
  const headerColumn = header === "column" || header === "both";
  const columns = Array.from(
    { length: tableColumnCount(table.rows) },
    (_, index) => index,
  );

  const cell = (
    row: { cells: TableCell[] },
    rowIndex: number,
    column: number,
    scope: "col" | "row" | undefined,
  ) => {
    const content = row.cells[column]?.content;
    // An empty header cell names nothing: it is a plain cell (the corner of
    // a table whose first row and first column are both headers).
    return h(
      scope && content ? "th" : "td",
      { key: column, scope: scope && content ? scope : undefined },
      content
        ? renderInlineRun(
            content,
            ["rows", String(rowIndex), "cells", String(column), "content"],
            text,
            editor,
          )
        : null,
    );
  };
  const row = (
    entry: { cells: TableCell[] },
    rowIndex: number,
    head: boolean,
  ) =>
    h(
      "tr",
      { key: rowIndex },
      columns.map((column) =>
        cell(
          entry,
          rowIndex,
          column,
          head ? "col" : headerColumn && column === 0 ? "row" : undefined,
        ),
      ),
    );
  const body = table.rows
    .map((entry, index) => ({ entry, index }))
    .slice(headerRow ? 1 : 0);

  return h(
    "section",
    {
      className: `site-block site-table site-table--${layout}`,
      "data-block-type": "core.table",
      "data-section-layout": layout,
    },
    h(
      "div",
      {
        className: "site-table__scroll",
        role: "region",
        "aria-label": table.caption || siteUiTexts(options?.locale).table,
        tabIndex: 0,
      },
      h(
        "table",
        null,
        table.caption
          ? h("caption", null, text(["caption"], table.caption))
          : null,
        headerRow ? h("thead", null, row(table.rows[0]!, 0, true)) : null,
        body.length > 0
          ? h(
              "tbody",
              null,
              body.map(({ entry, index }) => row(entry, index, false)),
            )
          : null,
      ),
    ),
  );
}
