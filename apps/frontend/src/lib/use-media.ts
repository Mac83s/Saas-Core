"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches, kept current. The server and the first
 * render say „no”, so a page renders its wide layout until the browser
 * answers — never a mismatch between the two.
 */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia?.(query);
      list?.addEventListener("change", onChange);
      return () => list?.removeEventListener("change", onChange);
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}
