import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without this, a second test in the same file queries a DOM that still holds
// the first render and every `getByRole` finds two matches. Files that already
// call `cleanup` in their own `afterEach` are unaffected — it is idempotent.
afterEach(cleanup);

// input-otp (the one-time-code field) mirrors the caret with timeouts (0, 10
// and 50 ms) after it mounts and after every change, and never clears them;
// torn down first, they fire into a gone `window` and vitest reports an
// unhandled error. The test remembers having shown the field: one in a dialog
// that closed again is gone from the DOM by the end, its timeouts are not.
// Hooks run in reverse order, so this one runs before cleanup.
const OTP_FIELD = "[data-input-otp]";
let otpShown = false;
if (
  typeof document !== "undefined" &&
  typeof MutationObserver !== "undefined"
) {
  new MutationObserver((records) => {
    if (otpShown) return;
    otpShown = records.some((record) =>
      Array.from(record.addedNodes).some(
        (node) =>
          node instanceof Element &&
          (node.matches(OTP_FIELD) || node.querySelector(OTP_FIELD) !== null),
      ),
    );
  }).observe(document, { childList: true, subtree: true });
}
afterEach(async () => {
  if (typeof document === "undefined") return;
  if (otpShown || document.querySelector(OTP_FIELD)) {
    otpShown = false;
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
});

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

// input-otp (the one-time-code field) watches its input with a ResizeObserver;
// jsdom has none and there is nothing to measure.
if (typeof window !== "undefined" && !("ResizeObserver" in window)) {
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    value: class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
}
