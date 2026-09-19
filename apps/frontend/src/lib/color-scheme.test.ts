import { afterEach, expect, test } from "vitest";

import { COLOR_SCHEME_SCRIPT, setColorScheme } from "./color-scheme";

afterEach(() => {
  delete document.documentElement.dataset.colorScheme;
  localStorage.clear();
});

test("ciemny wybór trafia na <html> i przeżywa przeładowanie", () => {
  setColorScheme("dark");
  expect(document.documentElement.dataset.colorScheme).toBe("dark");

  // A reload starts light; the head script restores the choice.
  delete document.documentElement.dataset.colorScheme;
  new Function(COLOR_SCHEME_SCRIPT)();
  expect(document.documentElement.dataset.colorScheme).toBe("dark");
});

test("jasny jest domyślny i zdejmuje atrybut", () => {
  new Function(COLOR_SCHEME_SCRIPT)();
  expect(document.documentElement.dataset.colorScheme).toBeUndefined();

  setColorScheme("dark");
  setColorScheme("light");
  expect(document.documentElement.dataset.colorScheme).toBeUndefined();
  expect(localStorage.getItem("color-scheme")).toBe("light");
});
