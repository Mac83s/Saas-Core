/** Letters Unicode normalisation cannot decompose, so stripping combining
 *  marks would delete them outright rather than fold them to a base letter —
 *  "Łódź" would become "odz". Mirrors `transliterate_label` in
 *  `shared/sites/domain_services.py`; the two must agree, or the panel would
 *  suggest an address the API then normalises to something else. */
const TRANSLITERATIONS = new Map<string, string>([
  ["ł", "l"],
  ["Ł", "L"],
  ["đ", "d"],
  ["Đ", "D"],
  ["ø", "o"],
  ["Ø", "O"],
  ["ß", "ss"],
  ["æ", "ae"],
  ["Æ", "AE"],
  ["œ", "oe"],
  ["Œ", "OE"],
  ["ı", "i"],
  ["İ", "I"],
  ["þ", "th"],
  ["Þ", "TH"],
  ["ð", "d"],
  ["Ð", "D"],
]);

/** Derives the URL-safe key a title implies: `Zażółć gęślą jaźń` becomes
 *  `zazolc-gesla-jazn`. Returns an empty string when nothing survives, which
 *  the caller shows as "no suggestion yet" rather than as an invalid value. */
export function slugifyTitle(value: string): string {
  const folded = Array.from(value)
    .map((char) => TRANSLITERATIONS.get(char) ?? char)
    .join("");
  return (
    folded
      .normalize("NFKD")
      .split("")
      // Combining diacritical marks, U+0300 to U+036F: NFKD split them off the
      // base letter above, and dropping them is what turns "ó" into "o".
      .filter((char) => {
        const code = char.charCodeAt(0);
        return code < 0x0300 || code > 0x036f;
      })
      .join("")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
  );
}

/** Cyrillic letters by BGN/PCGN without diacritics — mirrors
 *  `content_protocol/transliteration.py`, and the two answer the shared cases
 *  in `packages/contracts/locales/slug-cases.json`. */
const CYRILLIC_TO_LATIN = new Map<string, string>([
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

/** The German umlauts are written out, the rest as in `slugifyTitle`. */
const LANGUAGE_FOLDS = new Map<string, string>([
  ["ä", "ae"],
  ["ö", "oe"],
  ["ü", "ue"],
  ...[...TRANSLITERATIONS].filter(([letter]) => letter === letter.toLowerCase()),
]);

/** A language version's address from its title in that language (ADR-070
 *  pkt 18): `Über uns` → `ueber-uns`, `Наши услуги` → `nashi-uslugi`. The
 *  backend makes the same one, so the panel's suggestion is what gets saved. */
export function slugFromTitle(title: string, maxLength = 100): string {
  const latin = Array.from(title.toLowerCase())
    .map((char) => CYRILLIC_TO_LATIN.get(char) ?? char)
    .map((char) => LANGUAGE_FOLDS.get(char) ?? char)
    .join("");
  const slug = latin
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug.slice(0, maxLength).replace(/-+$/, "");
}
