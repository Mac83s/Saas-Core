/**
 * Does the catalogue route, and does it cover the repository?
 *
 * `ai:validate` asks whether a skill is well formed. This asks the two questions
 * that matter afterwards: for a task somebody actually has, does exactly one
 * description stand out — and is there a part of the product nobody wrote a
 * procedure for.
 *
 * What this is not: proof that a model picks the right skill. It cannot be —
 * that depends on the model. What it is: proof that the descriptions
 * *discriminate*, which is the half we control and the half that regresses. A
 * new skill whose description overlaps an existing one turns routing into a
 * coin flip, and that failure is silent — the agent reads a plausible
 * instruction for the wrong area and follows it.
 */

import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const CANONICAL_ROOT = path.join(repositoryRoot, ".agents/skills");
const EVALS = path.join(repositoryRoot, ".agents/evals/routing.json");
const MODULES = path.join(repositoryRoot, "packages/contracts/modules");

const problems = [];
const fail = (where, message) => problems.push(`${where}: ${message}`);

async function skillDescriptions() {
  const entries = await readdir(CANONICAL_ROOT, { withFileTypes: true });
  const descriptions = new Map();
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const source = (
      await readFile(path.join(CANONICAL_ROOT, entry.name, "SKILL.md"), "utf8")
    ).replaceAll(String.fromCharCode(13), "");
    const end = source.indexOf("\n---", 4);
    if (end === -1) continue;
    const line = source
      .slice(4, end)
      .split("\n")
      .find((row) => row.startsWith("description:"));
    if (line === undefined) continue;
    descriptions.set(
      entry.name,
      `${entry.name} ${line.slice(12)}`.toLowerCase(),
    );
  }
  return descriptions;
}

/** How many of a scenario's terms a description carries. */
const score = (haystack, terms) =>
  terms.filter((term) => haystack.includes(term.toLowerCase())).length;

async function main() {
  const evals = JSON.parse(await readFile(EVALS, "utf8"));
  const descriptions = await skillDescriptions();
  const seen = new Set();

  for (const scenario of evals.scenarios) {
    const where = `scenariusz ${scenario.id}`;
    if (seen.has(scenario.id)) fail(where, "zduplikowany identyfikator");
    seen.add(scenario.id);

    const expected = descriptions.get(scenario.expect);
    if (expected === undefined) {
      fail(where, `oczekuje skill ${scenario.expect}, którego nie ma`);
      continue;
    }
    const target = score(expected, scenario.terms);
    if (target < scenario.terms.length) {
      const missing = scenario.terms.filter(
        (term) => !expected.includes(term.toLowerCase()),
      );
      fail(
        where,
        `description skill ${scenario.expect} nie niesie terminów: ${missing.join(", ")}`,
      );
    }
    const rivals = [...descriptions]
      .filter(([name]) => name !== scenario.expect)
      .map(([name, haystack]) => [name, score(haystack, scenario.terms)])
      .filter(([, rival]) => rival >= target)
      .map(([name, rival]) => `${name} (${rival})`);
    if (rivals.length > 0) {
      fail(
        where,
        `${scenario.expect} (${target}) nie wygrywa z: ${rivals.join(", ")} — ` +
          "opisy przestały rozróżniać, routing byłby losowy",
      );
    }
  }

  const catalogued = (await readdir(MODULES))
    .filter((file) => file.endsWith(".json"))
    .map((file) => file.replace(/\.json$/, ""));
  for (const moduleId of catalogued) {
    const entry = evals.coverage[moduleId];
    if (entry === undefined) {
      fail(
        "pokrycie",
        `moduł ${moduleId} nie ma przypisanej procedury ani świadomego wyboru skill ogólnego`,
      );
      continue;
    }
    if (!descriptions.has(entry.skill)) {
      fail(
        "pokrycie",
        `moduł ${moduleId} wskazuje nieistniejący skill ${entry.skill}`,
      );
    }
    if (!entry.note || entry.note.length < 20) {
      fail("pokrycie", `moduł ${moduleId} nie mówi, dlaczego akurat ten skill`);
    }
  }
  for (const moduleId of Object.keys(evals.coverage)) {
    if (moduleId.startsWith("$")) continue;
    if (!catalogued.includes(moduleId)) {
      fail("pokrycie", `wpis dla nieistniejącego modułu ${moduleId}`);
    }
  }

  const unexercised = [...descriptions.keys()].filter(
    (name) =>
      !name.startsWith("memex") &&
      !evals.scenarios.some((scenario) => scenario.expect === name),
  );
  if (unexercised.length > 0) {
    fail(
      "scenariusze",
      `skill bez żadnego scenariusza: ${unexercised.join(", ")}`,
    );
  }

  if (problems.length > 0) {
    console.error("Evale routingu nie przeszły:");
    for (const problem of problems) console.error(`  - ${problem}`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `Routing rozstrzygnięty: ${evals.scenarios.length} scenariuszy, ` +
      `${catalogued.length} modułów pokrytych.`,
  );
}

await main();
