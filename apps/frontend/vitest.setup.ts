import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without this, a second test in the same file queries a DOM that still holds
// the first render and every `getByRole` finds two matches. Files that already
// call `cleanup` in their own `afterEach` are unaffected — it is idempotent.
afterEach(cleanup);

// jsdom has no PointerEvent, and Base UI forwards a switch's click as one
// (`dispatchClickWithModifiers`); a MouseEvent carries everything it reads.
if (typeof window !== "undefined" && !("PointerEvent" in window)) {
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: class PointerEvent extends MouseEvent {},
  });
}

// ProseMirror (the rich text editor) measures ranges and hit-tests points to
// keep the caret in view; jsdom has no layout, so both report nothing.
if (typeof Range !== "undefined") {
  Range.prototype.getClientRects = () =>
    ({
      length: 0,
      item: () => null,
      [Symbol.iterator]: [][Symbol.iterator],
    }) as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
}
if (typeof document !== "undefined") document.elementFromPoint = () => null;
