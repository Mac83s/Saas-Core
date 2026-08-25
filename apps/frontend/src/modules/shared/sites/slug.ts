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
