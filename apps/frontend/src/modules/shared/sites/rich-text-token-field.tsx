"use client";

/** A rich-text run in another language (TL15): the words are the
 *  translator's, the formatting is the source's. Each token — bold, italic, a
 *  link — shows as it looks on the page, may be moved and its words changed,
 *  but is never added, removed or split; a refused edit says why. The value
 *  is the unit's token string; the backend builds the HTML from it. */

import { Mark, mergeAttributes, type JSONContent } from "@tiptap/core";
import { Document } from "@tiptap/extension-document";
import { Paragraph } from "@tiptap/extension-paragraph";
import { Text } from "@tiptap/extension-text";
import { UndoRedo } from "@tiptap/extensions";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { EditorContent, useEditor } from "@tiptap/react";
import { useTranslations } from "next-intl";
import { createElement, useEffect, useRef, useState } from "react";

import {
  docToTokens,
  runsToDoc,
  tokenNumbers,
  tokenProblem,
  tokenRuns,
  type TokenMarks,
  type TokenProblem,
} from "./rich-text-tokens";

const LOAD = "tokenLoad";

function TokenMark(linkTitle: (href: string) => string) {
  return Mark.create({
    name: "token",
    // Typing at a token's edge stays outside it, as at a link's.
    inclusive: false,
    excludes: "",
    addAttributes: () => ({
      number: { default: null },
      bold: { default: null },
      italic: { default: null },
      href: { default: null },
      rel: { default: null },
    }),
    parseHTML: () => [{ tag: "[data-token]" }],
    renderHTML: ({ mark, HTMLAttributes }) => {
      const attrs = mark.attrs as TokenMarks & { number: number };
      const className = [
        "rich-text-token",
        attrs.bold ? "font-semibold" : "",
        attrs.italic ? "italic" : "",
        attrs.href ? "rich-text-token--link underline" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const own = {
        "data-token": String(attrs.number),
        class: className,
        // A link's accessible name is its words; the description says where
        // it leads, so a screen reader tells two links apart.
        ...(attrs.href ? { title: linkTitle(attrs.href) } : {}),
      };
      return [
        "span",
        mergeAttributes(
          Object.fromEntries(
            Object.entries(HTMLAttributes).filter(
              ([key]) =>
                !["number", "bold", "italic", "href", "rel"].includes(key),
            ),
          ),
          own,
        ),
        0,
      ];
    },
  });
}

function guard(
  expected: readonly number[],
  refuse: (problem: TokenProblem) => void,
) {
  return new Plugin({
    key: new PluginKey("tokenGuard"),
    filterTransaction: (tr) => {
      if (!tr.docChanged || tr.getMeta(LOAD)) return true;
      const problem = tokenProblem(
        docToTokens(tr.doc.toJSON() as JSONContent),
        expected,
      );
      if (problem === null) return true;
      refuse(problem);
      return false;
    },
  });
}

/** The field's document model: one paragraph of text and fixed tokens.
 *  `refuse` hears every edit the guard turned down. */
export function tokenFieldExtensions(
  linkTitle: (href: string) => string,
  expected: readonly number[],
  refuse: (problem: TokenProblem) => void,
) {
  return [
    Document,
    Paragraph,
    Text,
    UndoRedo,
    TokenMark(linkTitle).extend({
      addProseMirrorPlugins: () => [guard(expected, refuse)],
    }),
  ];
}

export interface TokenTextFieldProps {
  readonly id: string;
  /** The unit's text in this language, tokens included. */
  readonly value: string;
  readonly onChange: (value: string) => void;
  /** The source's text, whose tokens the value must keep. */
  readonly source: string;
  readonly marks: readonly TokenMarks[];
  readonly labelledBy: string;
  readonly describedBy?: string;
  readonly disabled?: boolean;
  /** Called with the reason an edit was refused, for the editor's
   *  `aria-live` notice. */
  readonly onRefused: (message: string) => void;
}

export function TokenTextField({
  id,
  value,
  onChange,
  source,
  marks,
  labelledBy,
  describedBy,
  disabled = false,
  onRefused,
}: TokenTextFieldProps) {
  const t = useTranslations("Sites.languageMode");
  const [expected] = useState(() => tokenNumbers(source));
  // The guard lives in the editor, created once; a refusal reaches the
  // caller's current handler through this channel rather than a stale one.
  const [refusals] = useState(() => new EventTarget());
  useEffect(() => {
    const listener = (event: Event) =>
      onRefused((event as CustomEvent<string>).detail);
    refusals.addEventListener("refused", listener);
    return () => refusals.removeEventListener("refused", listener);
  }, [onRefused, refusals]);
  const written = useRef(value);
  const editor = useEditor({
    immediatelyRender: false,
    editable: !disabled,
    extensions: tokenFieldExtensions(
      (href) => t("tokenLink", { href }),
      expected,
      (problem) =>
        refusals.dispatchEvent(
          new CustomEvent("refused", { detail: t(`refused.${problem}`) }),
        ),
    ),
    content: runsToDoc(tokenRuns(value), marks),
    editorProps: {
      attributes: {
        id,
        role: "textbox",
        "aria-multiline": "false",
        "aria-labelledby": labelledBy,
        ...(describedBy ? { "aria-describedby": describedBy } : {}),
        class:
          "min-h-9 rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
      },
      // One run of text: Enter would start a paragraph the source does not
      // have.
      handleKeyDown: (_view, event) => event.key === "Enter",
      // Pasted words take the formatting where they land, never their own.
      handlePaste: (view, event) => {
        const text = event.clipboardData?.getData("text/plain") ?? "";
        view.dispatch(view.state.tr.insertText(text.replace(/\s+/g, " ")));
        return true;
      },
      handleDrop: () => true,
    },
    onUpdate: ({ editor: current }) => {
      const next = docToTokens(current.getJSON());
      written.current = next;
      onChange(next);
    },
  });

  // A reload after a conflict, or "Zostaw bez zmian", replaces the value.
  useEffect(() => {
    if (!editor || value === written.current) return;
    written.current = value;
    editor
      .chain()
      .command(({ tr }) => {
        tr.setMeta(LOAD, true);
        return true;
      })
      .setContent(runsToDoc(tokenRuns(value), marks), { emitUpdate: false })
      .run();
  }, [editor, marks, value]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [disabled, editor]);

  return <EditorContent editor={editor} />;
}

/** The source's run as the page shows it, read-only, beside the field. */
export function TokenText({
  text,
  marks,
}: {
  text: string;
  marks: readonly TokenMarks[];
}) {
  const [runs] = useState(() => tokenRuns(text));
  return createElement(
    "span",
    null,
    ...runs.map((run, index) => {
      if (run.token === null) return run.text;
      const mark = marks[run.token - 1] ?? {};
      return createElement(
        "span",
        {
          key: index,
          className: [
            mark.bold ? "font-semibold" : "",
            mark.italic ? "italic" : "",
            mark.href ? "underline" : "",
          ]
            .filter(Boolean)
            .join(" "),
        },
        run.text,
      );
    }),
  );
}
