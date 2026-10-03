import { expect, test } from "vitest";

import {
  docToTokens,
  runsToDoc,
  tokenNumbers,
  tokenProblem,
  tokenRuns,
} from "./rich-text-tokens";

const SOURCE = "Przeczytaj ⟦1⟧naszą ofertę⟦/1⟧ albo ⟦2⟧partnera⟦/2⟧.";
const MARKS = [{ bold: true, href: "/oferta/" }, { href: "https://p.example" }];

test("a run's tokens become marked text and come back unchanged", () => {
  const doc = runsToDoc(tokenRuns(SOURCE), MARKS);
  expect(doc.content?.[0]?.content?.[1]).toEqual({
    type: "text",
    text: "naszą ofertę",
    marks: [
      { type: "token", attrs: { number: 1, bold: true, href: "/oferta/" } },
    ],
  });
  expect(docToTokens(doc)).toBe(SOURCE);
  expect(tokenNumbers(SOURCE)).toEqual([1, 2]);
});

test("words move around tokens; a token may move, never go or split", () => {
  const expected = tokenNumbers(SOURCE);
  expect(
    tokenProblem("Read ⟦2⟧the partner⟦/2⟧ or ⟦1⟧our offer⟦/1⟧.", expected),
  ).toBeNull();
  expect(tokenProblem("Read our offer or ⟦2⟧the partner⟦/2⟧.", expected)).toBe(
    "token_removed",
  );
  expect(tokenProblem("Read ⟦1⟧⟦/1⟧ or ⟦2⟧x⟦/2⟧.", expected)).toBe(
    "token_removed",
  );
  expect(
    tokenProblem("⟦1⟧our⟦/1⟧ new ⟦1⟧offer⟦/1⟧ and ⟦2⟧x⟦/2⟧", expected),
  ).toBe("token_split");
});

test("a bracket that does not pair is plain text", () => {
  expect(tokenRuns("a ⟦/3⟧ b ⟦9 c")).toEqual([
    { text: "a ⟦/3⟧ b ⟦9 c", token: null },
  ]);
});
