/**
 * Structured data for a JSON-LD script element (TL18); `JsonLd` in
 * `#components/json-ld` prints it, and nothing else does. The data carries
 * text a company wrote, so it is serialised where nothing in it can end the
 * element or the script: `<`, `>` and `&` as escapes, and the two line
 * separators JavaScript reads as line ends (U+2028, U+2029). JSON parsers
 * read every one of them back unchanged.
 */
const UNSAFE: Record<string, string> = {
  "<": "\\u003c",
  ">": "\\u003e",
  "&": "\\u0026",
  "\u2028": "\\u2028",
  "\u2029": "\\u2029",
};

export function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(
    /[<>&\u2028\u2029]/g,
    (character) => UNSAFE[character] ?? character,
  );
}
