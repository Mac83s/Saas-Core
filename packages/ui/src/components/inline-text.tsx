"use client";

import { useCallback, useRef, useState } from "react";

/** Plain text only: native inputs preserve selection, IME and paste semantics.
 *  The small local buffer is committed on blur/Enter; Escape discards it. */
export function InlineText({
  value,
  label,
  instructions,
  multiline = false,
  disabled = false,
  onCommit,
}: {
  value: string;
  label: string;
  instructions: string;
  multiline?: boolean;
  disabled?: boolean;
  onCommit: (value: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const finished = useRef(false);
  const focus = useCallback(
    (node: HTMLInputElement | HTMLTextAreaElement | null) => {
      if (node) {
        node.focus();
        node.select();
      }
    },
    [],
  );
  function finish(commit: boolean, restoreFocus = false) {
    if (finished.current || draft === null) return;
    finished.current = true;
    if (commit && !disabled && draft !== value) onCommit(draft);
    setDraft(null);
    if (restoreFocus) requestAnimationFrame(() => trigger.current?.focus());
  }
  const field = {
    ref: focus,
    value: draft ?? value,
    disabled,
    "aria-label": label,
    "aria-description": instructions,
    className:
      "max-w-full min-w-0 rounded border border-primary bg-background text-foreground outline-2 outline-primary",
    style: {
      font: "inherit",
      lineHeight: "inherit",
      textAlign: "inherit" as const,
      width: "100%",
    },
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => setDraft(event.target.value),
    onBlur: () => finish(true),
    onKeyDown: (
      event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => {
      if (event.nativeEvent.isComposing) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finish(false, true);
      } else if (
        event.key === "Enter" &&
        (!multiline || event.ctrlKey || event.metaKey)
      ) {
        event.preventDefault();
        event.stopPropagation();
        finish(true, true);
      }
    },
  };
  return (
    <span data-inline-text className="max-w-full">
      {draft === null ? (
        <button
          ref={trigger}
          type="button"
          disabled={disabled}
          aria-label={label}
          aria-description={instructions}
          className="max-w-full cursor-text whitespace-pre-wrap rounded hover:outline hover:outline-primary focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default"
          style={{
            font: "inherit",
            lineHeight: "inherit",
            textAlign: "inherit",
            // A button does not inherit it by default, so an uppercase label
            // or eyebrow would read differently here than when published.
            textTransform: "inherit",
            overflowWrap: "anywhere",
          }}
          onClick={() => {
            finished.current = false;
            setDraft(value);
          }}
        >
          {value}
        </button>
      ) : multiline ? (
        <textarea
          {...field}
          rows={Math.max(2, Math.min(8, draft.split("\n").length))}
        />
      ) : (
        <input {...field} type="text" />
      )}
    </span>
  );
}
