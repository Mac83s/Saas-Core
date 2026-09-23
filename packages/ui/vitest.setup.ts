import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without this, a second test in the same file queries a DOM that still holds
// the first render and every `getByRole` finds two matches.
afterEach(cleanup);

// jsdom has no PointerEvent, and Base UI forwards a switch's click as one
// (`dispatchClickWithModifiers`); a MouseEvent carries everything it reads.
if (typeof window !== "undefined" && !("PointerEvent" in window)) {
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: class PointerEvent extends MouseEvent {},
  });
}
