import { createElement as h, type ReactElement, type ReactNode } from "react";

import type {
  BlockEditor,
  BlockTextRenderer,
  FeatureListV5Data,
} from "./types";

/** feature_list v5 layouts (phase 4, F4-P1). Columns, groups, per-item notes
 *  and the section action exist from v5 on; the older layouts leave them out,
 *  which the editor reports as hidden fields. */
export const FEATURE_LIST_V5_LAYOUTS = [
  "scope_comparison",
  "shared_roles",
  "scope_limits",
  "staged_preparation",
  "instruction_notes",
  "fit_check",
] as const;

const VALUE_KEYS = ["first", "second", "third"] as const;

type Item = FeatureListV5Data["items"][number];

const step = (index: number) =>
  h(
    "span",
    { className: "site-section__step", "aria-hidden": true },
    String(index + 1).padStart(2, "0"),
  );

const heading = (
  level: "h3" | "h4",
  editor: BlockEditor | undefined,
  children: ReactNode,
) => h(level, editor ? { role: "presentation" } : null, children);

/** The section's one action. In the editor it is editable text without
 *  navigation, like every other action. */
export function featureListAction(
  data: FeatureListV5Data,
  text: BlockTextRenderer,
  editor?: BlockEditor,
): ReactElement | null {
  if (!data.action) return null;
  const { href, label } = data.action;
  return h(
    editor ? "span" : "a",
    {
      className: "site-section__action",
      href: editor ? undefined : href,
      rel: editor || !href.startsWith("https://") ? undefined : "noreferrer",
    },
    text(["action", "label"], label),
  );
}

/** Items in runs: an item with a `group` starts a new run under that title;
 *  items before the first titled one form a run without a title. */
function groups(items: readonly Item[]) {
  const runs: { title?: string; at: number; items: [Item, number][] }[] = [];
  items.forEach((item, index) => {
    if (runs.length === 0 || item.group)
      runs.push({ title: item.group, at: index, items: [] });
    runs[runs.length - 1].items.push([item, index]);
  });
  return runs;
}

function itemBody(
  item: Item,
  index: number,
  text: BlockTextRenderer,
  editor: BlockEditor | undefined,
  level: "h3" | "h4",
  withNote: boolean,
): ReactNode[] {
  const path = ["items", String(index)];
  return [
    heading(level, editor, text([...path, "title"], item.title)),
    item.text ? h("p", null, text([...path, "text"], item.text)) : null,
    withNote && item.note
      ? h(
          "p",
          { className: "site-section__item-note", role: "note" },
          text([...path, "note"], item.note),
        )
      : null,
  ];
}

/** The six v5 layouts, below the intro; `note` and `action` are the ones the
 *  caller built (the editor adapter records every text it renders). */
export function featureListV5Body(
  layout: (typeof FEATURE_LIST_V5_LAYOUTS)[number],
  data: FeatureListV5Data,
  text: BlockTextRenderer,
  editor: BlockEditor | undefined,
  note: ReactElement | null,
  action: ReactElement | null,
): ReactNode[] {
  const items = data.items;
  const columns = (data.columns ?? []).slice(0, VALUE_KEYS.length);
  if (layout === "scope_comparison") {
    // A table on a wide screen; a card per row on a phone, each value under
    // its column's name (CSS reads `data-label`). Explicit roles keep the
    // table semantics when CSS changes the display.
    const rows: ReactNode[] = [];
    for (const run of groups(items)) {
      if (run.title)
        rows.push(
          h(
            "tr",
            {
              key: `group-${run.at}`,
              role: "row",
              className: "site-section__table-group",
            },
            h(
              "th",
              {
                colSpan: columns.length + 1,
                scope: "rowgroup",
                role: "rowheader",
              },
              text(["items", String(run.at), "group"], run.title),
            ),
          ),
        );
      for (const [item, index] of run.items) {
        const path = ["items", String(index)];
        rows.push(
          h(
            "tr",
            { key: index, role: "row" },
            h(
              "th",
              { scope: "row", role: "rowheader" },
              h(
                "span",
                { className: "site-section__row-title" },
                text([...path, "title"], item.title),
              ),
              item.text
                ? h(
                    "span",
                    { className: "site-section__row-text" },
                    text([...path, "text"], item.text),
                  )
                : null,
            ),
            columns.map((column, position) => {
              const key = VALUE_KEYS[position];
              const value = item.values?.[key];
              return h(
                "td",
                { key, role: "cell", "data-label": column.title },
                value
                  ? text([...path, "values", key], value)
                  : h("span", { "aria-hidden": true }, "—"),
              );
            }),
          ),
        );
      }
    }
    return [
      h(
        "div",
        { key: "table", className: "site-section__table" },
        h(
          "table",
          { role: "table" },
          columns.length
            ? h(
                "thead",
                { role: "rowgroup" },
                h(
                  "tr",
                  { role: "row" },
                  h("td", { role: "cell" }),
                  columns.map((column, position) =>
                    h(
                      "th",
                      { key: position, scope: "col", role: "columnheader" },
                      h(
                        "span",
                        { className: "site-section__column-title" },
                        text(
                          ["columns", String(position), "title"],
                          column.title,
                        ),
                      ),
                      column.text
                        ? h(
                            "span",
                            { className: "site-section__column-text" },
                            text(
                              ["columns", String(position), "text"],
                              column.text,
                            ),
                          )
                        : null,
                    ),
                  ),
                ),
              )
            : null,
          h("tbody", { role: "rowgroup" }, rows),
        ),
      ),
      note,
      action,
    ];
  }
  if (layout === "shared_roles") {
    // Two lanes (yours and ours) along the same stages. The lane names head
    // the list once on a wide screen; on a phone each cell carries its own.
    const lanes = columns.slice(0, 2);
    return [
      lanes.length
        ? h(
            "div",
            {
              key: "lanes",
              className: "site-section__lanes",
              "aria-hidden": editor ? undefined : true,
            },
            lanes.map((lane, position) =>
              h(
                "p",
                { key: position },
                h(
                  "strong",
                  null,
                  text(["columns", String(position), "title"], lane.title),
                ),
                lane.text
                  ? h(
                      "span",
                      null,
                      text(["columns", String(position), "text"], lane.text),
                    )
                  : null,
              ),
            ),
          )
        : null,
      h(
        "ol",
        { key: "stages", className: "site-section__roles" },
        items.map((item, index) =>
          h(
            "li",
            { key: index },
            step(index),
            h(
              "div",
              { className: "site-section__role-stage" },
              ...itemBody(item, index, text, editor, "h3", false),
            ),
            lanes.map((lane, position) => {
              const key = VALUE_KEYS[position];
              const value = item.values?.[key];
              return value
                ? h(
                    "div",
                    { key, className: "site-section__lane", "data-lane": key },
                    h(
                      "p",
                      { className: "site-section__lane-label" },
                      lane.title,
                    ),
                    h(
                      "p",
                      null,
                      text(["items", String(index), "values", key], value),
                    ),
                  )
                : null;
            }),
          ),
        ),
      ),
      note,
      action,
    ];
  }
  if (layout === "scope_limits" || layout === "staged_preparation") {
    const runs = groups(items).map((run, position) =>
      h(
        layout === "scope_limits" ? "div" : "li",
        { key: run.at, className: "site-section__group" },
        layout === "staged_preparation" ? step(position) : null,
        h(
          "div",
          null,
          run.title
            ? heading(
                "h3",
                editor,
                text(["items", String(run.at), "group"], run.title),
              )
            : null,
          h(
            "ul",
            null,
            run.items.map(([item, index]) =>
              h(
                "li",
                { key: index },
                ...itemBody(
                  item,
                  index,
                  text,
                  editor,
                  "h4",
                  layout === "staged_preparation",
                ),
              ),
            ),
          ),
        ),
      ),
    );
    return [
      layout === "scope_limits"
        ? h("div", { key: "groups", className: "site-section__groups" }, runs)
        : h("ol", { key: "groups", className: "site-section__groups" }, runs),
      note,
      action,
    ];
  }
  if (layout === "instruction_notes")
    return [
      h(
        "ol",
        { key: "steps" },
        items.map((item, index) =>
          h(
            "li",
            { key: index },
            step(index),
            h("div", null, ...itemBody(item, index, text, editor, "h3", true)),
          ),
        ),
      ),
      note,
      action,
    ];
  // fit_check: criteria to recognise oneself in, then the verdict with the
  // section's action — the decision and the next step in one place.
  return [
    h(
      "ul",
      { key: "checks", className: "site-section__checks" },
      items.map((item, index) =>
        h(
          "li",
          { key: index },
          ...itemBody(item, index, text, editor, "h3", false),
        ),
      ),
    ),
    note || action
      ? h(
          "div",
          { key: "verdict", className: "site-section__verdict" },
          note,
          action,
        )
      : null,
  ];
}
