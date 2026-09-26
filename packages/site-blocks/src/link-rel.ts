import type { LinkRel } from "./types";

/** The `rel` a published link carries: `noreferrer` on the way out to another
 *  site, as always, plus how the link vouches for its target (ADR-061). */
export function linkRel(href: string, rel?: LinkRel): string | undefined {
  const parts = [
    ...(href.startsWith("https://") ? ["noreferrer"] : []),
    ...(rel ? [rel] : []),
  ];
  return parts.length ? parts.join(" ") : undefined;
}
