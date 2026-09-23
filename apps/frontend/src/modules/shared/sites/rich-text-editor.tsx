"use client";

/** The WYSIWYG editor for structured rich text (ADR-056): `core.rich_text`
 *  `content` and `aside.content`, written like a document instead of `**`
 *  markup. The surrounding RHF form keeps the value; the editor is loaded
 *  from it and writes the whole node array back after a pause in typing and
 *  when it loses focus — one undo step, like the other buffered fields. A
 *  value changed from outside (undo, the canvas, a template) reloads it. */

import { Extension, type Editor } from "@tiptap/core";
import { ListKeymap } from "@tiptap/extension-list";
import { Placeholder, UndoRedo } from "@tiptap/extensions";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import {
  BoldIcon,
  IndentIcon,
  ItalicIcon,
  LinkIcon,
  ListIcon,
  ListOrderedIcon,
  OutdentIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { richTextAnchorSlug, type RichTextNode } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Toolbar,
  ToolbarButton,
  ToolbarSeparator,
  ToolbarToggle,
} from "@saas-core/ui/components/toolbar";

import { DraftHistoryContext } from "./draft-history";
import { fromEditorDoc, toEditorDoc } from "./rich-text-doc";
import { collectAnchors, useErrorText } from "./rich-text-field";
import { isRichTextHref } from "./rich-text-markup";
import { richTextExtensions, type RichTextNodeType } from "./rich-text-schema";

const IDLE_COMMIT_MS = 700;
const SETTLE = "richTextSettle";
const LEVELS = [2, 3, 4] as const;

/** How many lists hold the caret: the contract allows two levels. */
function listDepth(editor: Editor): number {
  const { $from } = editor.state.selection;
  let depth = 0;
  for (let level = $from.depth; level > 0; level -= 1) {
    const type = $from.node(level).type.name;
    if (type === "bulletList" || type === "orderedList") depth += 1;
  }
  return depth;
}

/** Marks are allowed here: not in a heading. */
const canLink = (editor: Editor) => editor.can().setMark("link", { href: "/" });

/** Each heading's anchor as a quiet `#anchor` after its text: where a link
 *  to that place points. Not part of the document. */
const AnchorHints = Extension.create({
  name: "richTextAnchorHints",
  addProseMirrorPlugins: () => [
    new Plugin({
      props: {
        decorations: (state) => {
          const hints: Decoration[] = [];
          state.doc.descendants((node, position) => {
            if (node.type.name !== "heading" || !node.attrs.anchor) return;
            hints.push(
              Decoration.widget(
                position + node.nodeSize - 1,
                () => {
                  const hint = document.createElement("span");
                  hint.className = "rich-text-editor__anchor";
                  hint.setAttribute("aria-hidden", "true");
                  hint.textContent = `#${String(node.attrs.anchor)}`;
                  return hint;
                },
                { side: 1, ignoreSelection: true },
              ),
            );
          });
          return DecorationSet.create(state.doc, hints);
        },
      },
    }),
  ],
});

type RichTextEditorProps = {
  /** RHF path of the node array, e.g. `blocks.3.data.content`. */
  name: string;
  label: string;
  disabled?: boolean;
  /** The aside allows only `["paragraph", "list"]`. */
  allowedNodes?: readonly RichTextNodeType[];
};

/** One editor per path: the editor's callbacks are bound when it is created,
 *  so a section that moves (and changes its path) gets a fresh one. */
export function RichTextEditor(props: RichTextEditorProps) {
  return <PathEditor key={props.name} {...props} />;
}

function PathEditor({
  name,
  label,
  disabled = false,
  allowedNodes,
}: RichTextEditorProps) {
  const t = useTranslations("Sites.richText");
  const id = useId();
  const { control, getValues, setValue } = useFormContext();
  const stored = JSON.stringify(
    (useWatch({ control, name }) as RichTextNode[] | undefined) ?? [],
  );
  const error = useErrorText(name)("");
  const history = useContext(DraftHistoryContext);
  const [linking, setLinking] = useState(false);
  // The JSON both sides agree on: what was loaded or last written.
  const written = useRef(stored);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const allows = (type: RichTextNodeType) =>
    !allowedNodes || allowedNodes.includes(type);

  /** Anchors for headings that got text since the last write, and fresh
   *  ones for copies: section and heading anchors are one namespace per
   *  page, so the other sections' anchors count too. */
  function settleAnchors(editor: Editor) {
    const own = collectAnchors(getValues(name));
    const taken = new Set(
      collectAnchors(getValues("blocks") ?? []).filter((anchor) => {
        const index = own.indexOf(anchor);
        if (index === -1) return true;
        own.splice(index, 1);
        return false;
      }),
    );
    const { tr } = editor.state;
    editor.state.doc.descendants((node, position) => {
      if (node.type.name !== "heading") return;
      const anchor = node.attrs.anchor as string | null;
      if (anchor && !taken.has(anchor)) {
        taken.add(anchor);
        return;
      }
      if (!node.textContent) return;
      const fresh = richTextAnchorSlug(node.textContent, taken);
      taken.add(fresh);
      tr.setNodeAttribute(position, "anchor", fresh);
    });
    if (tr.docChanged) editor.view.dispatch(tr.setMeta(SETTLE, true));
  }

  function commit(editor: Editor) {
    clearTimeout(timer.current);
    timer.current = undefined;
    if (editor.isDestroyed) return;
    settleAnchors(editor);
    const nodes = fromEditorDoc(editor.getJSON());
    const json = JSON.stringify(nodes);
    if (json === written.current) return;
    written.current = json;
    setValue(name, nodes, { shouldDirty: true, shouldValidate: true });
  }

  function historyStep(direction: "undo" | "redo", editor: Editor) {
    // Typing not yet written becomes its own step first, so undo takes back
    // exactly what was just typed.
    if (timer.current !== undefined) commit(editor);
    history?.[direction]();
    return true;
  }

  const editor = useEditor({
    immediatelyRender: false,
    editable: !disabled,
    extensions: [
      ...richTextExtensions(allowedNodes),
      ...(allows("list") ? [ListKeymap] : []),
      Placeholder.configure({ placeholder: t("editor.placeholder") }),
      AnchorHints,
      // Outside the page editor there is no page history to join.
      ...(history ? [] : [UndoRedo]),
      Extension.create({
        name: "richTextKeys",
        priority: 1000,
        addKeyboardShortcuts() {
          return {
            "Mod-k": ({ editor }) => {
              if (canLink(editor)) setLinking(true);
              return true;
            },
            // A third list level is not in the contract.
            Tab: ({ editor }) =>
              editor.isActive("listItem") && listDepth(editor) >= 2,
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
    content: toEditorDoc(JSON.parse(stored) as RichTextNode[]),
    editorProps: {
      attributes: {
        id: `${id}-text`,
        role: "textbox",
        "aria-multiline": "true",
        "aria-labelledby": `${id}-label`,
        "aria-describedby": `${id}-hint`,
        class: "rich-text-editor__content",
      },
    },
    onUpdate: ({ editor, transaction }) => {
      if (transaction.getMeta(SETTLE)) return;
      clearTimeout(timer.current);
      timer.current = setTimeout(() => commit(editor), IDLE_COMMIT_MS);
    },
    onBlur: ({ editor }) => commit(editor),
  });

  // A value changed elsewhere replaces the text; the caret stays near where
  // it was.
  useEffect(() => {
    if (!editor || stored === written.current) return;
    clearTimeout(timer.current);
    timer.current = undefined;
    written.current = stored;
    const caret = editor.state.selection.from;
    editor.commands.setContent(
      toEditorDoc(JSON.parse(stored) as RichTextNode[]),
      { emitUpdate: false },
    );
    editor.commands.setTextSelection(
      Math.min(caret, editor.state.doc.content.size),
    );
  }, [editor, stored]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  // Leaving the section with typing still pending writes it.
  useEffect(
    () => () => {
      if (editor && timer.current !== undefined) commit(editor);
    },
    // commit reads only refs and stable form methods.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor],
  );

  return (
    <Field className="rich-text-editor" data-invalid={Boolean(error)}>
      {/* The text is a contentEditable element, which a label cannot target:
          it takes its name from aria-labelledby, a click focuses it. */}
      <FieldLabel id={`${id}-label`} onClick={() => editor?.commands.focus()}>
        {label}
      </FieldLabel>
      <FieldDescription id={`${id}-hint`}>{t("editor.hint")}</FieldDescription>
      <EditorToolbar
        allows={allows}
        disabled={disabled}
        editor={editor}
        onLink={() => setLinking(true)}
        textId={`${id}-text`}
      />
      <EditorContent editor={editor} />
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

function EditorToolbar({
  allows,
  disabled,
  editor,
  onLink,
  textId,
}: {
  allows: (type: RichTextNodeType) => boolean;
  disabled: boolean;
  editor: Editor | null;
  onLink: () => void;
  textId: string;
}) {
  const t = useTranslations("Sites.richText");
  const state = useEditorState({
    editor,
    selector: ({ editor }) =>
      editor
        ? {
            bold: editor.isActive("bold"),
            italic: editor.isActive("italic"),
            link: editor.isActive("link"),
            // Headings take no marks (the contract keeps them plain text).
            marks: canLink(editor),
            bullet: editor.isActive("bulletList"),
            ordered: editor.isActive("orderedList"),
            inList: editor.isActive("listItem"),
            canIndent:
              editor.can().sinkListItem("listItem") && listDepth(editor) < 2,
            canOutdent: editor.can().liftListItem("listItem"),
            level:
              LEVELS.find((level) => editor.isActive("heading", { level })) ??
              0,
          }
        : null,
  });
  if (!editor || !state) return null;
  const run = () => editor.chain().focus();
  // Keeps the caret in the text: the toolbar never takes focus on a click.
  const keep = { onMouseDown: (event: MouseEvent) => event.preventDefault() };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {allows("heading") && (
        <div className="w-48 shrink-0">
          <NativeSelect
            aria-controls={textId}
            aria-label={t("editor.blockStyle")}
            disabled={disabled || state.inList}
            onChange={(event) => {
              const level = Number(event.target.value);
              if (level)
                run()
                  .setHeading({ level: level as 2 | 3 | 4 })
                  .run();
              else run().setParagraph().run();
            }}
            value={String(state.level)}
          >
            <option value="0">{t("editor.paragraph")}</option>
            {LEVELS.map((level) => (
              <option key={level} value={level}>
                {t(`levels.h${level}`)}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      <Toolbar
        aria-controls={textId}
        aria-label={t("formatting")}
        disabled={disabled}
      >
        <ToolbarToggle
          {...keep}
          aria-label={t("bold")}
          disabled={!state.marks}
          onPressedChange={() => run().toggleBold().run()}
          pressed={state.bold}
        >
          <BoldIcon aria-hidden />
        </ToolbarToggle>
        <ToolbarToggle
          {...keep}
          aria-label={t("italic")}
          disabled={!state.marks}
          onPressedChange={() => run().toggleItalic().run()}
          pressed={state.italic}
        >
          <ItalicIcon aria-hidden />
        </ToolbarToggle>
        <ToolbarToggle
          {...keep}
          aria-label={t("editor.link")}
          disabled={!state.marks}
          onPressedChange={onLink}
          pressed={state.link}
        >
          <LinkIcon aria-hidden />
        </ToolbarToggle>
        {allows("list") && (
          <>
            <ToolbarSeparator />
            <ToolbarToggle
              {...keep}
              aria-label={t("insert.bulletList")}
              onPressedChange={() => run().toggleBulletList().run()}
              pressed={state.bullet}
            >
              <ListIcon aria-hidden />
            </ToolbarToggle>
            <ToolbarToggle
              {...keep}
              aria-label={t("insert.orderedList")}
              onPressedChange={() => run().toggleOrderedList().run()}
              pressed={state.ordered}
            >
              <ListOrderedIcon aria-hidden />
            </ToolbarToggle>
            <ToolbarButton
              {...keep}
              aria-label={t("editor.indent")}
              disabled={!state.canIndent}
              onClick={() => run().sinkListItem("listItem").run()}
            >
              <IndentIcon aria-hidden />
            </ToolbarButton>
            <ToolbarButton
              {...keep}
              aria-label={t("editor.outdent")}
              disabled={!state.canOutdent}
              onClick={() => run().liftListItem("listItem").run()}
            >
              <OutdentIcon aria-hidden />
            </ToolbarButton>
          </>
        )}
      </Toolbar>
    </div>
  );
}

/** Adds, changes or removes the link at the caret. With nothing selected
 *  outside a link, the address itself becomes the linked text. Mounted while
 *  open, so it starts from the link under the caret. There is no `<form>`:
 *  the dialog renders inside the page form's React tree. */
function LinkDialog({
  editor,
  onClose,
  pageAnchors,
}: {
  editor: Editor;
  onClose: () => void;
  pageAnchors: readonly string[];
}) {
  const t = useTranslations("Sites.richText");
  const common = useTranslations("Common");
  const id = useId();
  const [current] = useState(
    () => editor.getAttributes("link").href as string | undefined,
  );
  const [href, setHref] = useState(current ?? "");
  const [invalid, setInvalid] = useState(false);
  const anchors = [...new Set(pageAnchors)].sort();

  function apply() {
    const address = href.trim();
    if (!isRichTextHref(address)) {
      setInvalid(true);
      return;
    }
    const chain = editor.chain().focus();
    if (editor.state.selection.empty && !editor.isActive("link"))
      chain
        .insertContent({
          type: "text",
          text: address,
          marks: [{ type: "link", attrs: { href: address } }],
        })
        .run();
    else chain.extendMarkRange("link").setLink({ href: address }).run();
    onClose();
  }

  function remove() {
    editor.chain().focus().extendMarkRange("link").unsetLink().run();
    onClose();
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      open
    >
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("editor.link")}</DialogTitle>
        </DialogHeader>
        <Field data-invalid={invalid}>
          <FieldLabel htmlFor={`${id}-href`}>{t("linkUrl")}</FieldLabel>
          <Input
            aria-describedby={`${id}-href-hint`}
            aria-invalid={invalid}
            autoComplete="off"
            id={`${id}-href`}
            inputMode="url"
            onChange={(event) => {
              setHref(event.target.value);
              setInvalid(false);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              apply();
            }}
            value={href}
          />
          <FieldDescription id={`${id}-href-hint`}>
            {t("linkHint")}
          </FieldDescription>
          {invalid && <FieldError>{t("linkInvalid")}</FieldError>}
        </Field>
        {anchors.length > 0 && (
          <Field>
            <FieldLabel htmlFor={`${id}-anchor`}>
              {t("editor.pagePlace")}
            </FieldLabel>
            <NativeSelect
              id={`${id}-anchor`}
              onChange={(event) => {
                if (event.target.value) setHref(`#${event.target.value}`);
                setInvalid(false);
              }}
              value={href.startsWith("#") ? href.slice(1) : ""}
            >
              <option value="">{t("editor.pagePlaceNone")}</option>
              {anchors.map((anchor) => (
                <option key={anchor} value={anchor}>
                  #{anchor}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}
        <DialogFooter>
          {current !== undefined && (
            <Button onClick={remove} type="button" variant="outline">
              {t("editor.linkRemove")}
            </Button>
          )}
          <Button onClick={onClose} type="button" variant="ghost">
            {t("linkCancel")}
          </Button>
          <Button onClick={apply} type="button">
            {t("linkApply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
