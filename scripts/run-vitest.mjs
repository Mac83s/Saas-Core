import path from "node:path";
import { spawnSync } from "node:child_process";

const environment = { ...process.env };
if (process.platform !== "win32") {
  environment.TMPDIR = "/tmp";
  environment.TMP = "/tmp";
  environment.TEMP = "/tmp";
}

const cli = path.join(process.cwd(), "node_modules/vitest/vitest.mjs");
const result = spawnSync(
  process.execPath,
  [cli, "run", ...process.argv.slice(2)],
  {
    env: environment,
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
