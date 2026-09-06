/**
 * The deterministic half of the skills system.
 *
 * A skill is an instruction an agent will follow without a person in the loop,
 * so the ways it can quietly stop being useful all have to be mechanical
 * failures rather than things somebody notices later: a description that no
 * longer routes, a path that moved, a command that was renamed, an adapter
 * whose frontmatter drifted from the canonical file. A model reviewing its own
 * instructions is not an independent check; this is.
 *
 * What it cannot check — whether the advice is good — is what the scenarios and
 * a human reviewer are for.
 */

import { readFile, readdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const CANONICAL_ROOT = path.join(repositoryRoot, ".agents/skills");
const ADAPTER_ROOT = path.join(repositoryRoot, ".claude/skills");

/** Skills a tool mirrors byte for byte; they are not ours to keep thin. */
const MANAGED_MIRRORS = new Set(["memex", "memex-tidy", "memex-worklog"]);

/** An adapter that is not a mirror repeats the frontmatter and points home. */
const ADAPTER_MAX_BYTES = 1_200;

/** Long enough to be worth reading, short enough that it gets read. */
const SKILL_MAX_BYTES = 16_000;
const DESCRIPTION_MAX = 600;

/** Only these prefixes are treated as repository paths worth checking. */
const PATH_PREFIXES = [
  "apps/",
  "packages/",
  "docs/",
  "deployments/",
  "infra/",
  "scripts/",
  "Plan/",
  ".agents/",
  ".claude/",
  ".github/",
];

/** `pnpm` words that are not scripts in package.json. */
const PNPM_BUILTINS = new Set([
  "add",
  "dlx",
  "exec",
  "install",
  "remove",
  "run",
  "why",
]);

/**
 * Commands a skill may discuss but must never hand somebody to run.
 *
 * Only fenced code blocks are searched, because that is the difference between
 * explaining a rule and issuing an instruction: `verify-saas-core-release` says
 * in prose that `git push` happens only when the owner asks, and that sentence
 * is the opposite of authorizing it. This is the checkable part of "a skill may
 * not widen permissions"; the rest — an instruction that reads innocently and
 * grants more than it should — stays a question for review.
 */
const IRREVERSIBLE_IN_COMMANDS = [
  /\bgit\s+push\b/,
  /\bgit\s+reset\s+--hard\b/,
  /\brm\s+-rf\b/,
  /\bdocker\s+compose\s+down\s+.*-v\b/,
  /\bDROP\s+(TABLE|DATABASE|SCHEMA)\b/i,
  /\bTRUNCATE\b/i,
  /--apply\b/,
  /--force\b/,
];

const SECRET_PATTERNS = [
  /\bsk_(live|test)_[A-Za-z0-9]/,
  /\bwhsec_[A-Za-z0-9]/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\bghp_[A-Za-z0-9]{20,}/,
];

const problems = [];
const fail = (where, message) => problems.push(`${where}: ${message}`);

function parseFrontmatter(source, where) {
  if (!source.startsWith("---\n")) {
    fail(where, "brak frontmatteru; plik musi zaczynać się od `---`");
    return null;
  }
  const end = source.indexOf("\n---", 4);
  if (end === -1) {
    fail(where, "frontmatter nie jest domknięty");
    return null;
  }
  const fields = {};
  for (const line of source.slice(4, end).split("\n")) {
    if (!line.trim()) continue;
    const separator = line.indexOf(":");
    if (separator === -1) {
      fail(where, `nie umiem odczytać linii frontmatteru: ${line}`);
      continue;
    }
    fields[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }
  return { fields, body: source.slice(end + 4) };
}

/** Windows checkouts carry CR; the rules are about content, not line endings. */
const readText = async (file) =>
  (await readFile(file, "utf8")).replaceAll(String.fromCharCode(13), "");

async function exists(relative) {
  try {
    await stat(path.join(repositoryRoot, relative));
    return true;
  } catch {
    return false;
  }
}

async function listSkills(root) {
  try {
    const entries = await readdir(root, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
  } catch {
    return [];
  }
}

async function checkReferences(name, body, scripts) {
  const where = `.agents/skills/${name}`;
  for (const match of body.matchAll(/`([^`\n]+)`/g)) {
    const token = match[1].trim();
    if (!PATH_PREFIXES.some((prefix) => token.startsWith(prefix))) continue;
    if (/[<>*?{}$\s]/.test(token)) continue;
    const target = token.replace(/[.,;:)]+$/, "");
    if (!(await exists(target))) {
      fail(where, `wskazuje ścieżkę, której nie ma: ${target}`);
    }
  }
  for (const match of body.matchAll(/\bpnpm ([a-z][a-z0-9:._-]*)/g)) {
    const script = match[1];
    if (PNPM_BUILTINS.has(script)) continue;
    if (!scripts.has(script)) {
      fail(
        where,
        `wskazuje polecenie, którego nie ma w package.json: pnpm ${script}`,
      );
    }
  }
  for (const pattern of SECRET_PATTERNS) {
    if (pattern.test(body)) fail(where, "treść wygląda na zawierającą sekret");
  }
  for (const block of body.matchAll(/```[^\n]*\n([\s\S]*?)```/g)) {
    for (const pattern of IRREVERSIBLE_IN_COMMANDS) {
      if (pattern.test(block[1])) {
        fail(
          where,
          "blok poleceń zawiera operację nieodwracalną albo produkcyjną " +
            `(${pattern.source}); skill nie autoryzuje takich działań`,
        );
      }
    }
  }
}

async function checkRoutingMap(names) {
  const source = await readFile(path.join(repositoryRoot, "AGENTS.md"), "utf8");
  const section = source.split("## Mapa ścieżek do skills")[1];
  if (section === undefined) {
    fail("AGENTS.md", "brak sekcji `## Mapa ścieżek do skills`");
    return;
  }
  const rows = section
    .split("\n## ")[0]
    .split("\n")
    .filter((line) => line.startsWith("|") && line.includes("`"));
  if (rows.length < 2) {
    fail("AGENTS.md", "mapa ścieżek jest pusta");
    return;
  }
  const routed = new Set();
  for (const row of rows) {
    const cells = row.split("|");
    if (cells.length < 3) continue;
    for (const match of cells[1].matchAll(/`([^`]+)`/g)) {
      const target = match[1].trim();
      if (!PATH_PREFIXES.some((prefix) => target.startsWith(prefix))) continue;
      if (!(await exists(target))) {
        fail("AGENTS.md", `mapa wskazuje ścieżkę, której nie ma: ${target}`);
      }
    }
    for (const match of cells[2].matchAll(/`([^`]+)`/g)) {
      const skill = match[1].trim();
      routed.add(skill);
      if (!names.has(skill)) {
        fail("AGENTS.md", `mapa kieruje do nieistniejącego skill: ${skill}`);
      }
    }
  }
  for (const name of names) {
    if (MANAGED_MIRRORS.has(name)) continue;
    if (!routed.has(name)) {
      fail(
        "AGENTS.md",
        `skill ${name} nie ma żadnego wiersza w mapie ścieżek — nikt go nie znajdzie`,
      );
    }
  }
}

async function main() {
  const packageJson = JSON.parse(
    await readFile(path.join(repositoryRoot, "package.json"), "utf8"),
  );
  const scripts = new Set(Object.keys(packageJson.scripts ?? {}));

  const canonical = await listSkills(CANONICAL_ROOT);
  const adapters = await listSkills(ADAPTER_ROOT);
  if (canonical.length === 0) {
    fail(".agents/skills", "katalog skills jest pusty");
  }

  const names = new Set();
  const descriptions = new Map();

  for (const name of canonical) {
    const where = `.agents/skills/${name}`;
    const file = path.join(CANONICAL_ROOT, name, "SKILL.md");
    let source;
    try {
      source = await readText(file);
    } catch {
      fail(where, "brak SKILL.md");
      continue;
    }
    if (Buffer.byteLength(source, "utf8") > SKILL_MAX_BYTES) {
      fail(where, `SKILL.md przekracza ${SKILL_MAX_BYTES} bajtów`);
    }
    const parsed = parseFrontmatter(source, where);
    if (parsed === null) continue;
    const { fields, body } = parsed;

    if (fields.name !== name) {
      fail(
        where,
        `frontmatter name=${fields.name ?? "<brak>"} nie zgadza się z katalogiem`,
      );
    }
    if (names.has(name)) fail(where, "zduplikowana nazwa skill");
    names.add(name);

    const description = fields.description ?? "";
    if (description.length < 40) {
      fail(where, "description jest za krótki, żeby cokolwiek wyroutować");
    }
    if (description.length > DESCRIPTION_MAX) {
      fail(where, `description przekracza ${DESCRIPTION_MAX} znaków`);
    }
    const duplicate = descriptions.get(description);
    if (duplicate !== undefined) {
      fail(
        where,
        `description jest identyczny jak w ${duplicate} — routing byłby losowy`,
      );
    }
    descriptions.set(description, name);

    await checkReferences(name, body, scripts);

    // The adapter is what a client actually reads. Frontmatter decides which
    // skill gets picked, so a drifted description turns routing off silently.
    const adapterFile = path.join(ADAPTER_ROOT, name, "SKILL.md");
    let adapterSource;
    try {
      adapterSource = await readText(adapterFile);
    } catch {
      // A managed mirror is published by its own tool, which decides how many
      // of its skills a client needs; ours have to be reachable.
      if (!MANAGED_MIRRORS.has(name)) {
        fail(where, `brak adaptera .claude/skills/${name}/SKILL.md`);
      }
      continue;
    }
    if (MANAGED_MIRRORS.has(name)) {
      if (adapterSource !== source) {
        fail(
          `.claude/skills/${name}`,
          "mirror rozjechał się z kanonicznym plikiem",
        );
      }
      continue;
    }
    const adapterParsed = parseFrontmatter(
      adapterSource,
      `.claude/skills/${name}`,
    );
    if (adapterParsed === null) continue;
    if (adapterParsed.fields.name !== fields.name) {
      fail(
        `.claude/skills/${name}`,
        "name adaptera nie zgadza się z kanonicznym",
      );
    }
    if (adapterParsed.fields.description !== description) {
      fail(
        `.claude/skills/${name}`,
        "description adaptera nie zgadza się z kanonicznym — routing przestaje działać po cichu",
      );
    }
    if (Buffer.byteLength(adapterSource, "utf8") > ADAPTER_MAX_BYTES) {
      fail(
        `.claude/skills/${name}`,
        `adapter ma być cienki (limit ${ADAPTER_MAX_BYTES} bajtów), nie kopią treści`,
      );
    }
    if (!adapterParsed.body.includes(`.agents/skills/${name}/SKILL.md`)) {
      fail(`.claude/skills/${name}`, "adapter nie wskazuje kanonicznego pliku");
    }
  }

  for (const name of adapters) {
    if (!names.has(name)) {
      fail(
        `.claude/skills/${name}`,
        "adapter bez kanonicznego skill w .agents/skills",
      );
    }
  }

  await checkRoutingMap(names);

  if (problems.length > 0) {
    console.error("Walidacja skills nie przeszła:");
    for (const problem of problems) console.error(`  - ${problem}`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `Skills poprawne: ${names.size} kanonicznych, ${adapters.length} adapterów.`,
  );
}

await main();
