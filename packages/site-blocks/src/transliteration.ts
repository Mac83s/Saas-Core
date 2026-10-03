/** Cyrillic letters by BGN/PCGN without diacritics — mirrors
 *  `content_protocol/transliteration.py`, and the two answer the shared cases
 *  in `packages/contracts/locales/slug-cases.json`. One table in TypeScript:
 *  the panel's address suggestion and a heading's anchor both read it, so
 *  `Наши услуги` is `nashi-uslugi` in an address and in a link to a heading. */
export const CYRILLIC_TO_LATIN: ReadonlyMap<string, string> = new Map([
  ["а", "a"],
  ["б", "b"],
  ["в", "v"],
  ["г", "g"],
  ["д", "d"],
  ["е", "e"],
  ["ё", "e"],
  ["ж", "zh"],
  ["з", "z"],
  ["и", "i"],
  ["й", "y"],
  ["к", "k"],
  ["л", "l"],
  ["м", "m"],
  ["н", "n"],
  ["о", "o"],
  ["п", "p"],
  ["р", "r"],
  ["с", "s"],
  ["т", "t"],
  ["у", "u"],
  ["ф", "f"],
  ["х", "kh"],
  ["ц", "ts"],
  ["ч", "ch"],
  ["ш", "sh"],
  ["щ", "shch"],
  ["ъ", ""],
  ["ы", "y"],
  ["ь", ""],
  ["э", "e"],
  ["ю", "yu"],
  ["я", "ya"],
]);

/** The German letters written out, as in an address (`Über` → `ueber`). */
export const GERMAN_TO_LATIN: ReadonlyMap<string, string> = new Map([
  ["ä", "ae"],
  ["ö", "oe"],
  ["ü", "ue"],
  ["ß", "ss"],
]);
