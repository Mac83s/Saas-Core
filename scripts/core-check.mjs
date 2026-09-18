#!/usr/bin/env node
/**
 * ADR-049: a product repository never changes a file it received from
 * Saas-Core, so the core can be merged into it again and again without
 * conflicts. SEOSiteAudit and SeoContentRank edited their template, and that
 * is why their template can no longer be updated.
 *
 * Compares the tree with the core commit the product stands on
 * (`.saas-core-upstream`, written by `pnpm core:update`). Added files are the
 * product's own; a changed or deleted file of the core is a violation, unless
 * it is one of the product's slots or a file generated for its profile.
 * Saas-Core itself has no marker, and there is nothing to check.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const MARKER = ".saas-core-upstream";

/** The only core files a product may change. A trailing slash is a directory. */
const PRODUCT_OWNED = [
  "product.json",
  "README.md",
  ".mcp.json",
  "apps/frontend/src/product/",
  // Generated for the product's own profile. After a merge, regenerate them
  // (`pnpm api:schema`, `pnpm deployment:render`) instead of resolving by hand.
  "packages/contracts/openapi/v1.yaml",
  "packages/api-client/src/schema.d.ts",
  "apps/frontend/src/generated/deployment.ts",
];

const owned = (file) =>
  PRODUCT_OWNED.some((entry) =>
    entry.endsWith("/") ? file.startsWith(entry) : file === entry,
  );

if (!existsSync(MARKER)) {
  console.log("Brak .saas-core-upstream: to jest Saas-Core, nie produkt.");
  process.exit(0);
}

const base = readFileSync(MARKER, "utf8").trim();
let diff;
try {
  diff = execFileSync(
    "git",
    ["diff", "--no-renames", "--name-status", base, "--"],
    {
      encoding: "utf8",
    },
  );
} catch {
  console.error(
    `Commita rdzenia ${base} nie ma w historii — płytki klon? Pobierz pełną historię (fetch-depth: 0).`,
  );
  process.exit(1);
}

const violations = diff
  .split("\n")
  .filter(Boolean)
  .map((line) => line.split("\t"))
  .filter(([status, file]) => status !== "A" && !owned(file))
  .map(([status, file]) => `  ${status} ${file}`);

if (violations.length > 0) {
  console.error(
    [
      "Zmienione pliki rdzenia Saas-Core (ADR-049). Zmień je w Saas-Core i weź przez `pnpm core:update`:",
      ...violations,
    ].join("\n"),
  );
  process.exit(1);
}
console.log(`Rdzeń nietknięty względem Saas-Core ${base.slice(0, 12)}.`);
