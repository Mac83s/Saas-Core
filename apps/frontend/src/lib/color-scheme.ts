/**
 * Light by default; dark only when the person picks it (panel header). The
 * choice is a per-browser convenience, so it lives in localStorage — never
 * anything a session depends on.
 */
export type ColorScheme = "light" | "dark";

const KEY = "color-scheme";
const EVENT = "color-scheme-change";

/** Runs in <head> before first paint, so a dark choice does not flash light. */
export const COLOR_SCHEME_SCRIPT = `try{if(localStorage.getItem("${KEY}")==="dark")document.documentElement.dataset.colorScheme="dark"}catch(e){}`;

export function currentColorScheme(): ColorScheme {
  return document.documentElement.dataset.colorScheme === "dark"
    ? "dark"
    : "light";
}

export function setColorScheme(scheme: ColorScheme) {
  if (scheme === "dark") document.documentElement.dataset.colorScheme = "dark";
  else delete document.documentElement.dataset.colorScheme;
  try {
    localStorage.setItem(KEY, scheme);
  } catch {
    // Private mode or blocked storage: the choice lasts until reload.
  }
  window.dispatchEvent(new Event(EVENT));
}

export function subscribeColorScheme(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}
