import { expect, test } from "vitest";

import en from "../../messages/en.json";
import pl from "../../messages/pl.json";
import { mergeMessages } from "./merge-messages";
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

test("produkt dokłada klucze na każdej głębokości i nie gubi kluczy rdzenia", () => {
  const merged = mergeMessages(
    { History: { title: "Historia", actions: { a: "A", b: "B" } } },
    { History: { actions: { b: "B2", own: "Własna" } }, Product: { x: "X" } },
  );
  expect(merged).toEqual({
    History: { title: "Historia", actions: { a: "A", b: "B2", own: "Własna" } },
    Product: { x: "X" },
  });
});

function strings(value: object, prefix = ""): [string, string][] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof entry === "object" && entry !== null
      ? strings(entry, path)
      : [[path, String(entry)] as [string, string]];
  });
}

test("polski nie zgaduje rodzaju osoby, która czyta panel (UX-020)", () => {
  // „dokupiłeś”, „jesteś zalogowany”, „gdy będziesz gotowy”: the panel does
  // not know who reads it, so it says what happened, not who did it.
  const gendered =
    /\p{L}+(?:łeś|łaś)(?![\p{L}])|\b(?:jesteś|będziesz)\s+(?:zalogowan|gotow|pewn)\p{L}*/iu;
  expect(strings(pl).filter(([, text]) => gendered.test(text))).toEqual([]);
});
