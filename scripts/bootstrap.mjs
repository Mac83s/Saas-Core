import { spawnSync } from "node:child_process";

const profileFlag = process.argv.indexOf("--profile");
const profile = profileFlag >= 0 ? process.argv[profileFlag + 1] : "core-only";

if (!/^[a-z][a-z0-9-]*$/.test(profile)) {
  throw new Error(`Nieprawidłowy profil deploymentu: ${profile}`);
}

const nodeMajor = Number.parseInt(process.versions.node.split(".")[0], 10);
if (nodeMajor !== 24) {
  throw new Error(
    `Bootstrap wymaga Node.js 24 LTS; wykryto ${process.versions.node}`,
  );
}

const steps = [
  ["Instalacja workspace JavaScript", "pnpm", ["install", "--frozen-lockfile"]],
  [
    "Instalacja backendu",
    "uv",
    ["sync", "--project", "apps/backend", "--python", "3.14", "--frozen"],
  ],
  [
    "Uruchomienie PostgreSQL i Redis",
    "docker",
    ["compose", "up", "-d", "postgres", "redis"],
  ],
  [
    "Walidacja profilu",
    "node",
    ["packages/contracts/scripts/deployment-check.mjs", "--profile", profile],
  ],
  [
    "Generowanie profilu publicznego",
    "node",
    ["packages/contracts/scripts/deployment-render.mjs", "--profile", profile],
  ],
  [
    "Migracje Django",
    "uv",
    [
      "run",
      "--project",
      "apps/backend",
      "python",
      "apps/backend/manage.py",
      "migrate",
    ],
  ],
  ["Generowanie OpenAPI", "pnpm", ["api:schema"]],
  ["Generowanie klienta API", "pnpm", ["api:client"]],
];

for (const [label, command, args] of steps) {
  console.log(`\n==> ${label}`);
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

console.log(`\nBootstrap profilu ${profile} zakończony.`);
