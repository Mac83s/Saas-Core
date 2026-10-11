import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without this, a second test in the same file queries a DOM that still holds
// the first render and every `getByRole` finds two matches.
afterEach(cleanup);

// input-otp (the one-time-code field) mirrors the caret with timeouts after a
// focus; torn down first, they fire into a gone `window` and vitest reports an
// unhandled error. Hooks run in reverse order, so this one runs before cleanup.
afterEach(async () => {
  if (
    typeof document !== "undefined" &&
    document.querySelector("[data-input-otp]")
  ) {
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
