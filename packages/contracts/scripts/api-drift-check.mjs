import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const canonicalSchema = path.join(
  repositoryRoot,
  "packages/contracts/openapi/v1.yaml",
);
const canonicalClient = path.join(
  repositoryRoot,
  "packages/api-client/src/schema.d.ts",
);
const backendPython = path.join(
  repositoryRoot,
  "apps/backend/.venv/bin/python",
);
const openapiTypescriptCli = path.join(
  repositoryRoot,
  "node_modules/openapi-typescript/bin/cli.js",
);
const temporaryRoot = process.platform === "win32" ? tmpdir() : "/tmp";
const temporaryDirectory = await mkdtemp(
  path.join(temporaryRoot, "saas-core-api-"),
);
const temporarySchema = path.join(temporaryDirectory, "v1.yaml");
const temporaryClient = path.join(temporaryDirectory, "schema.d.ts");

const run = (command, args) => {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    throw new Error(
      `${command} zakończył się błędem:\n${result.stdout}${result.stderr}`,
    );
  }
};

const normalized = async (filePath) =>
  (await readFile(filePath, "utf8")).replaceAll("\r\n", "\n");

try {
  run(backendPython, [
    "apps/backend/manage.py",
    "spectacular",
    "--file",
    temporarySchema,
    "--validate",
    "--settings=saas_core.config.settings.test",
  ]);
  run(process.execPath, [
    openapiTypescriptCli,
    temporarySchema,
    "-o",
    temporaryClient,
  ]);

  if (
    (await normalized(canonicalSchema)) !== (await normalized(temporarySchema))
  ) {
    throw new Error("Drift OpenAPI: uruchom `pnpm api:schema`");
  }
  if (
    (await normalized(canonicalClient)) !== (await normalized(temporaryClient))
  ) {
    throw new Error("Drift klienta API: uruchom `pnpm api:client`");
  }
  console.log("OpenAPI i klient TypeScript są aktualne");
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
