"use client";

import { createContext } from "react";

/** What a control deep in the page form needs from the page editor: its
 *  undo and redo (Ctrl+Z in the rich text editor is the page's undo, not a
 *  second history) and the page's look (the full-screen writer uses its
 *  fonts). Absent outside the page editor, e.g. in blog entries. */
export const PageEditorContext = createContext<{
  undo: () => void;
  redo: () => void;
  look: string;
} | null>(null);
