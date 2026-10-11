"use client";

/** The grid editor of a `core.table` section: cells are written in place,
 *  like in a document, with rich text's marks (bold, italic, a link) and
 *  nothing the contract cannot hold. Rows and columns change only through
 *  the buttons, so the grid stays a rectangle. The surrounding RHF form keeps
 *  the value: the editor is loaded from it and writes all rows back after a
 *  pause in typing and when it loses focus, as the rich text editor does
 *  (ADR-056) — Ctrl+Z is the page's undo where there is a page history. */

import { Extension, type Editor } from "@tiptap/core";
import { UndoRedo } from "@tiptap/extensions";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import {
  BoldIcon,
  ItalicIcon,
  LinkIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { useFormContext, useWatch } from "react-hook-form";

import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@saas-core/ui/components/field";
import {
  Toolbar,
  ToolbarButton,
  ToolbarSeparator,
  ToolbarToggle,
} from "@saas-core/ui/components/toolbar";

import { PageEditorContext } from "./page-editor-context";
import {
  canonicalJson,
  collectAnchors,
  IDLE_COMMIT_MS,
  LinkDialog,
  useErrorText,
} from "./rich-text-editor";
import {
  fromTableDoc,
  MAX_TABLE_COLUMNS,
  MAX_TABLE_ROWS,
  TABLE_SHAPE,
  tableExtensions,
  toTableDoc,
  type TableRows,
} from "./table-doc";

type TableEditorProps = {
  /** RHF path of the rows, e.g. `blocks.3.data.rows`. */
  name: string;
  /** RHF path of the block's `header` choice: its cells look like headers. */
  headerName: string;
  label: string;
  disabled?: boolean;
};

/** Undo and redo reset the page form, and the section's fields mount again:
 *  an editor leaving with the caret hands it to the next editor of its path,
 *  so Ctrl+Z, Ctrl+Y can be pressed in a row (as in the rich text editor). */
const handover = new Map<string, number>();

/** One editor per path, like the rich text editor: a section that moves gets
 *  a fresh one. */
export function TableEditor(props: TableEditorProps) {
  return <PathEditor key={props.name} {...props} />;
}

const tableOf = (doc: ProseMirrorNode) => doc.firstChild!;

/** The row and column holding the caret (0, 0 before the editor has one). */
function caretCell(editor: Editor): { row: number; column: number } {
  const { $from } = editor.state.selection;
  return $from.depth >= 3
    ? { row: $from.index(1), column: $from.index(2) }
    : { row: 0, column: 0 };
}

/** Where a row starts, and where the text of one of its cells does. */
function rowStart(doc: ProseMirrorNode, row: number): number {
  let position = 1;
  for (let index = 0; index < row; index += 1)
    position += tableOf(doc).child(index).nodeSize;
  return position;
}
function cellStart(doc: ProseMirrorNode, row: number, column: number): number {
  let position = rowStart(doc, row) + 1;
  for (let index = 0; index < column; index += 1)
    position += tableOf(doc).child(row).child(index).nodeSize;
  return position;
}

/** The caret into a cell, its text selected: typing replaces it, as moving
 *  through a spreadsheet does. */
function selectCell(editor: Editor, row: number, column: number): boolean {
  const start = cellStart(editor.state.doc, row, column) + 1;
  const size = tableOf(editor.state.doc).child(row).child(column).content.size;
  return editor
    .chain()
    .focus()
    .setTextSelection({ from: start, to: start + size })
    .run();
}

function changeShape(
  editor: Editor,
  change: (tr: Editor["state"]["tr"], doc: ProseMirrorNode) => number,
): void {
  const { state, view } = editor;
  const tr = state.tr.setMeta(TABLE_SHAPE, true);
  const caret = change(tr, state.doc);
  tr.setSelection(TextSelection.near(tr.doc.resolve(caret)));
  view.dispatch(tr);
  view.focus();
}

function addRow(editor: Editor): void {
  const { row } = caretCell(editor);
  changeShape(editor, (tr, doc) => {
    const { tableRow, tableCell } = doc.type.schema.nodes;
    const columns = tableOf(doc).child(0).childCount;
    const at = rowStart(doc, row) + tableOf(doc).child(row).nodeSize;
    tr.insert(
      at,
      tableRow!.create(
        null,
        Array.from({ length: columns }, () => tableCell!.create()),
      ),
    );
    return at + 2;
  });
}

function deleteRow(editor: Editor): void {
  const { row } = caretCell(editor);
  changeShape(editor, (tr, doc) => {
    const at = rowStart(doc, row);
    tr.delete(at, at + tableOf(doc).child(row).nodeSize);
    return Math.min(at + 2, tr.doc.content.size - 3);
  });
}

function addColumn(editor: Editor): void {
  const { row, column } = caretCell(editor);
  changeShape(editor, (tr, doc) => {
    const { tableCell } = doc.type.schema.nodes;
    const rows = tableOf(doc).childCount;
    // From the last row up: an insert never moves a position still to use.
    for (let index = rows - 1; index >= 0; index -= 1)
      tr.insert(
        cellStart(doc, index, column) +
          tableOf(doc).child(index).child(column).nodeSize,
        tableCell!.create(),
      );
    return (
      tr.mapping.map(cellStart(doc, row, column)) +
      tableOf(doc).child(row).child(column).nodeSize +
      1
    );
  });
}

function deleteColumn(editor: Editor): void {
  const { row, column } = caretCell(editor);
  changeShape(editor, (tr, doc) => {
    const rows = tableOf(doc).childCount;
    for (let index = rows - 1; index >= 0; index -= 1) {
      const at = cellStart(doc, index, column);
      tr.delete(at, at + tableOf(doc).child(index).child(column).nodeSize);
    }
    return tr.mapping.map(cellStart(doc, row, column)) + 1;
  });
}

function PathEditor({
  name,
  headerName,
  label,
  disabled = false,
}: TableEditorProps) {
  const t = useTranslations("Sites.tableEditor");
  const rich = useTranslations("Sites.richText");
  const id = useId();
  const { control, getValues, setValue } = useFormContext();
  const stored = JSON.stringify(
    (useWatch({ control, name }) as TableRows | undefined) ?? [],
  );
  const header = (useWatch({ control, name: headerName }) as string) || "row";
  const error = useErrorText(name)("");
  // The page's history; outside the page editor there is none to join.
  const history = useContext(PageEditorContext);
  const [linking, setLinking] = useState(false);
  // The JSON both sides agree on: what was loaded or last written.
  const written = useRef(stored);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  function commit(editor: Editor) {
    clearTimeout(timer.current);
    timer.current = undefined;
    if (editor.isDestroyed) return;
    const rows = fromTableDoc(editor.getJSON());
    const json = JSON.stringify(rows);
    if (json === written.current) return;
    // Same grid, keys in another order (as the rich text editor): no change.
    if (canonicalJson(rows) === canonicalJson(JSON.parse(written.current)))
      return;
    written.current = json;
    setValue(name, rows, { shouldDirty: true, shouldValidate: true });
  }

  function historyStep(direction: "undo" | "redo", editor: Editor) {
    // Typing not yet written becomes its own step first.
    if (timer.current !== undefined) commit(editor);
    history?.[direction]();
    return true;
  }

  const editor = useEditor({
    immediatelyRender: false,
    editable: !disabled,
    extensions: [
      ...tableExtensions(),
      ...(history ? [] : [UndoRedo]),
      Extension.create({
        name: "tableKeys",
        priority: 1000,
        addKeyboardShortcuts() {
          return {
            "Mod-k": () => {
              setLinking(true);
              return true;
            },
            // Tab walks the cells and leaves after the last one, so the
            // keyboard is never held inside the grid.
            Tab: ({ editor }) => {
              const { row, column } = caretCell(editor);
              const table = tableOf(editor.state.doc);
              if (column + 1 < table.child(row).childCount)
                return selectCell(editor, row, column + 1);
              if (row + 1 < table.childCount)
                return selectCell(editor, row + 1, 0);
              return false;
            },
            "Shift-Tab": ({ editor }) => {
              const { row, column } = caretCell(editor);
              if (column > 0) return selectCell(editor, row, column - 1);
              if (row > 0)
                return selectCell(
                  editor,
                  row - 1,
                  tableOf(editor.state.doc).child(row - 1).childCount - 1,
                );
              return false;
            },
            // A cell is one run of text: Enter goes down the column instead
            // of splitting the cell in two.
            Enter: ({ editor }) => {
              const { row, column } = caretCell(editor);
              if (row + 1 < tableOf(editor.state.doc).childCount)
                selectCell(editor, row + 1, column);
              return true;
            },
            "Shift-Enter": () => true,
            ...(history
              ? {
                  "Mod-z": ({ editor }) => historyStep("undo", editor),
                  "Shift-Mod-z": ({ editor }) => historyStep("redo", editor),
                  "Mod-y": ({ editor }) => historyStep("redo", editor),
                }
              : {}),
          };
        },
      }),
    ],
    content: toTableDoc(JSON.parse(stored) as TableRows),
    editorProps: {
      attributes: {
        id: `${id}-grid`,
        role: "textbox",
        "aria-multiline": "true",
        "aria-labelledby": `${id}-label`,
        "aria-describedby": `${id}-hint`,
        class: "table-editor__content",
      },
      // Pasted words land in the cell under the caret as plain text; a
      // pasted table would otherwise bring its own cells.
      handlePaste: (view, event) => {
        const text = event.clipboardData?.getData("text/plain") ?? "";
        if (text)
          view.dispatch(view.state.tr.insertText(text.replace(/\s+/g, " ")));
        return true;
      },
      handleDrop: () => true,
    },
    onUpdate: ({ editor }) => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => commit(editor), IDLE_COMMIT_MS);
    },
    onBlur: ({ editor }) => commit(editor),
  });

  // A value changed elsewhere (undo, a template) replaces the grid. The
  // form's current value decides, not this render's (see the rich text
  // editor).
  useEffect(() => {
    if (!editor) return;
    const current = JSON.stringify(
      (getValues(name) as TableRows | undefined) ?? [],
    );
    if (current === written.current) return;
    clearTimeout(timer.current);
    timer.current = undefined;
    written.current = current;
    editor
      .chain()
      .command(({ tr }) => {
        tr.setMeta(TABLE_SHAPE, true);
        return true;
      })
      .setContent(toTableDoc(JSON.parse(current) as TableRows), {
        emitUpdate: false,
      })
      .run();
  }, [editor, stored, getValues, name]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  // Layout effects: the leaving editor's cleanup runs while its grid is still
  // in the page with focus, and before the next editor's effect.
  useLayoutEffect(() => {
    if (!editor) return;
    let frame = 0;
    const caret = handover.get(name);
    if (caret !== undefined) {
      handover.delete(name);
      const at = Math.min(caret, editor.state.doc.content.size);
      editor.commands.focus(at);
      // The page editor is a dialog: a frame after the old grid left the
      // page it takes focus back to itself. The caret returns after that.
      frame = requestAnimationFrame(() => {
        if (!editor.isDestroyed) editor.commands.focus(at);
      });
    }
    return () => {
      cancelAnimationFrame(frame);
      if (!editor.isDestroyed && editor.view.hasFocus())
        handover.set(name, editor.state.selection.from);
    };
  }, [editor, name]);

  // Leaving the section with typing still pending writes it.
  useEffect(
    () => () => {
      if (editor && timer.current !== undefined) commit(editor);
    },
    // commit reads only refs and stable form methods.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor],
  );

  const state = useEditorState({
    editor,
    selector: ({ editor }) =>
      editor
        ? {
            bold: editor.isActive("bold"),
            italic: editor.isActive("italic"),
            link: editor.isActive("link"),
            ...caretCell(editor),
            rows: tableOf(editor.state.doc).childCount,
            columns: tableOf(editor.state.doc).child(0).childCount,
          }
        : null,
  });
  // Keeps the caret in the grid: the toolbar never takes focus on a click.
  const keep = { onMouseDown: (event: MouseEvent) => event.preventDefault() };

  return (
    <Field
      className="table-editor"
      data-field-name={name}
      data-invalid={Boolean(error)}
    >
      {/* The grid is a contentEditable element, which a label cannot target:
          it takes its name from aria-labelledby, a click focuses it. */}
      <FieldLabel id={`${id}-label`} onClick={() => editor?.commands.focus()}>
        {label}
      </FieldLabel>
      <FieldDescription id={`${id}-hint`}>{t("hint")}</FieldDescription>
      {editor && state && (
        <Toolbar
          aria-controls={`${id}-grid`}
          aria-label={t("toolbar")}
          className="flex-wrap"
          disabled={disabled}
        >
          <ToolbarToggle
            {...keep}
            aria-label={rich("bold")}
            onPressedChange={() => editor.chain().focus().toggleBold().run()}
            pressed={state.bold}
          >
            <BoldIcon aria-hidden />
          </ToolbarToggle>
          <ToolbarToggle
            {...keep}
            aria-label={rich("italic")}
            onPressedChange={() => editor.chain().focus().toggleItalic().run()}
            pressed={state.italic}
          >
            <ItalicIcon aria-hidden />
          </ToolbarToggle>
          <ToolbarToggle
            {...keep}
            aria-label={rich("editor.link")}
            onPressedChange={() => setLinking(true)}
            pressed={state.link}
          >
            <LinkIcon aria-hidden />
          </ToolbarToggle>
          <ToolbarSeparator />
          <ToolbarButton
            {...keep}
            disabled={state.rows >= MAX_TABLE_ROWS}
            onClick={() => addRow(editor)}
          >
            <PlusIcon aria-hidden />
            {t("addRow")}
          </ToolbarButton>
          <ToolbarButton
            {...keep}
            disabled={state.columns >= MAX_TABLE_COLUMNS}
            onClick={() => addColumn(editor)}
          >
            <PlusIcon aria-hidden />
            {t("addColumn")}
          </ToolbarButton>
          <ToolbarButton
            {...keep}
            disabled={state.rows <= 1}
            onClick={() => deleteRow(editor)}
          >
            <Trash2Icon aria-hidden />
            {t("deleteRow")}
          </ToolbarButton>
          <ToolbarButton
            {...keep}
            disabled={state.columns <= 1}
            onClick={() => deleteColumn(editor)}
          >
            <Trash2Icon aria-hidden />
            {t("deleteColumn")}
          </ToolbarButton>
        </Toolbar>
      )}
      <div className="table-editor__scroll" data-header={header}>
        <EditorContent editor={editor} />
      </div>
      {state && (
        <p
          aria-live="polite"
          className="text-sm text-muted-foreground"
          role="status"
        >
          {t("position", {
            row: state.row + 1,
            column: state.column + 1,
            rows: state.rows,
            columns: state.columns,
          })}
        </p>
      )}
      <FieldError>{error}</FieldError>
      {editor && linking && (
        <LinkDialog
          editor={editor}
          onClose={() => setLinking(false)}
          pageAnchors={collectAnchors(getValues("blocks") ?? [])}
        />
      )}
    </Field>
  );
}
