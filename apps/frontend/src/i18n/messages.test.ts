import { expect, test } from "vitest";

import en from "../../messages/en.json";
import pl from "../../messages/pl.json";
import { routing } from "./routing";

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof entry === "object" && entry !== null
      ? keys(entry, path)
      : [path];
  });
}

test("katalogi PL i EN mają identyczny zestaw kluczy", () => {
  expect(keys(en).sort()).toEqual(keys(pl).sort());
});

test("polski jest jawnym fallbackiem routingu", () => {
  expect(routing.defaultLocale).toBe("pl");
  expect(routing.locales).toEqual(["pl", "en"]);
});
