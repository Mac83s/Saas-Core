import { expect, test } from "vitest";

import en from "../../messages/en.json";
import pl from "../../messages/pl.json";
import { layerMessages, mergeMessages, siteLayers } from "./merge-messages";
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
  // The panel's two first, then the profile's content languages (TL17).
  expect(routing.locales.slice(0, 2)).toEqual(["pl", "en"]);
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

test("słowa publicznych stron produktu leżą na wierzchu, a w języku treści pod spodem jest ich angielski (ADR-080)", () => {
  const core = { Common: { save: "Save" }, Catalog: { title: "Catalogue" } };
  const guest = { Catalog: { title: "Katalog (de)" } };
  const site = {
    pl: { Site: { menu: "Rasy", quiz: "Quiz" } },
    en: { Site: { menu: "Breeds", quiz: "Quiz", footer: "About" } },
    de: { Site: { menu: "Rassen" } },
  };

  // A content language: the English catalogue, the product's English words,
  // the guest pages' texts, then the product's own words in it.
  expect(layerMessages(core, siteLayers(site, "de", "en", guest))).toEqual({
    Common: { save: "Save" },
    Catalog: { title: "Katalog (de)" },
    Site: { menu: "Rassen", quiz: "Quiz", footer: "About" },
  });
  // A panel language reads its own catalogue and its own words only.
  expect(layerMessages(core, siteLayers(site, "en", "en", {}))).toEqual({
    ...core,
    Site: { menu: "Breeds", quiz: "Quiz", footer: "About" },
  });
  expect(layerMessages(core, siteLayers(site, "pl", "pl", {})).Site).toEqual({
    menu: "Rasy",
    quiz: "Quiz",
  });
  // A product without public pages changes nothing.
  expect(
    layerMessages(core, [undefined, ...siteLayers({}, "de", "en", guest)]),
  ).toEqual(mergeMessages(mergeMessages(core, {}), guest));
});
