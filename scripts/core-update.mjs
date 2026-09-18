#!/usr/bin/env node
/**
 * Takes the current Saas-Core into a product repository (ADR-049): merges
 * `upstream/main` (or the ref given) and records the core commit the product
 * now stands on, which is what `pnpm core:check` compares against.
 *
 *   pnpm core:update            # upstream/main
 *   pnpm core:update v1.4.0     # a tag or commit of Saas-Core
 */
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";

/** The same marker `scripts/core-check.mjs` reads. */
const MARKER = ".saas-core-upstream";

const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();
const ref = process.argv[2] ?? "upstream/main";

git("fetch", "upstream", "--tags");
const target = git("rev-parse", `${ref}^{commit}`);
const current = existsSync(MARKER) ? readFileSync(MARKER, "utf8").trim() : "";
if (target === current) {
  console.log(`Już na Saas-Core ${target.slice(0, 12)}.`);
  process.exit(0);
}

writeFileSync(MARKER, `${target}\n`);
const merge = spawnSync("git", ["merge", "--no-ff", "--no-commit", target], {
  stdio: "inherit",
});
git("add", MARKER);

const next =
  "Potem: pnpm install, pnpm api:schema, pnpm deployment:render, pnpm deployment:artifact, testy.";
if (merge.status !== 0) {
  console.error(
    `Konflikty przy merge'u Saas-Core ${target.slice(0, 12)}. Pliki generowane wygeneruj od nowa, resztę rozwiąż, potem git commit. ${next}`,
  );
  process.exit(1);
}
git(
  "commit",
  "--no-edit",
  "-m",
  `chore(core): Saas-Core ${target.slice(0, 12)}`,
);
console.log(`Produkt stoi na Saas-Core ${target.slice(0, 12)}. ${next}`);
