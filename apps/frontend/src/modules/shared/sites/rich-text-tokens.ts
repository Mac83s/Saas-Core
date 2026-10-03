/** A translated rich-text run is a string with numbered tokens around the
 *  source's marked spans: `Przeczytaj ⟦1⟧naszą ofertę⟦/1⟧.` (ADR-070). The
 *  backend checks the tokens and builds the published HTML from the source's
 *  spans and this string (`assemble`), so the panel never serialises rich
 *  text in a language version — it only moves words around fixed tokens. */

import type { JSONContent } from "@tiptap/core";

/** What one token marks in the source: `⟦n⟧` is entry n-1 of a unit's
 *  `marks` (LocaleBodyUnit). */
export interface TokenMarks {
  readonly bold?: boolean;
  readonly italic?: boolean;
  readonly href?: string;
  readonly rel?: string;
}

export interface TokenRun {
  readonly text: string;
  /** The token around this text, 1-based; null outside every token. */
  readonly token: number | null;
}

const TOKEN = /⟦(\/?)(\d{1,3})⟧/g;

/** Splits a unit's text into runs. A bracket that does not form a token
 *  pair is plain text, as on the backend. */
export function tokenRuns(text: string): TokenRun[] {
  const runs: TokenRun[] = [];
  let open: number | null = null;
  let cursor = 0;
  let buffer = "";
  const flush = () => {
    if (buffer) runs.push({ text: buffer, token: open });
    buffer = "";
  };
  for (const match of text.matchAll(TOKEN)) {
    const [whole, closing, digits] = match;
    const number = Number(digits);
    const at = match.index ?? 0;
    buffer += text.slice(cursor, at);
    cursor = at + whole.length;
    if (!closing && open === null) {
      flush();
      open = number;
    } else if (closing && open === number) {
      flush();
      open = null;
    } else {
      buffer += whole;
    }
  }
  buffer += text.slice(cursor);
  flush();
  return runs;
}

/** The token numbers a unit's source text uses, in order. */
export function tokenNumbers(text: string): number[] {
  return tokenRuns(text).flatMap((run) =>
    run.token === null ? [] : [run.token],
  );
}

export function runsToDoc(
  runs: readonly TokenRun[],
  marks: readonly TokenMarks[],
): JSONContent {
  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: runs
          .filter((run) => run.text)
          .map((run) =>
            run.token === null
              ? { type: "text", text: run.text }
              : {
                  type: "text",
                  text: run.text,
                  marks: [
                    {
                      type: "token",
                      attrs: { number: run.token, ...marks[run.token - 1] },
                    },
                  ],
                },
          ),
      },
    ],
  };
}

/** The doc back to a unit's text: each token's text between its numbers. */
export function docToTokens(doc: JSONContent): string {
  const nodes = doc.content?.[0]?.content ?? [];
  let out = "";
  let open: number | null = null;
  for (const node of nodes) {
    const token = node.marks?.find((mark) => mark.type === "token");
    const number = token ? Number(token.attrs?.number) : null;
    if (number !== open) {
      if (open !== null) out += `⟦/${open}⟧`;
      if (number !== null) out += `⟦${number}⟧`;
      open = number;
    }
    out += node.text ?? "";
  }
  if (open !== null) out += `⟦/${open}⟧`;
  return out;
}

export type TokenProblem = "token_removed" | "token_split";

/** Why a text may not stand for the source's: a token gone, or one now in
 *  two places. Moving a token or changing the words inside it is fine. */
export function tokenProblem(
  text: string,
  expected: readonly number[],
): TokenProblem | null {
  const counts = new Map<number, number>();
  // Adjacent runs of one token are one range; a second range is a split.
  let previous: number | null = null;
  for (const run of tokenRuns(text)) {
    if (!run.text) continue;
    if (run.token !== null && run.token !== previous) {
      counts.set(run.token, (counts.get(run.token) ?? 0) + 1);
    }
    previous = run.token;
  }
  if (expected.some((number) => !counts.has(number))) return "token_removed";
  if ([...counts.values()].some((count) => count > 1)) return "token_split";
  return null;
}
