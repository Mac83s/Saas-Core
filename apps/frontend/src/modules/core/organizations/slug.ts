/**
 * A URL-safe identifier derived from the name. The slug is unique across the
 * platform and nobody should have to invent one on their first screen, so a
 * short random tail keeps two "Gospodarstwo Nowak" apart.
 */
export function slugFromName(name: string): string {
  const base =
    name
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/ł/g, "l")
      .replace(/Ł/g, "L")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "organizacja";
  const tail = crypto.getRandomValues(new Uint32Array(1))[0].toString(36);
  return `${base}-${tail.slice(0, 4)}`;
}
