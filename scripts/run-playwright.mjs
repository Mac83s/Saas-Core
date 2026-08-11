import path from "node:path";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const environment = { ...process.env };
if (process.platform !== "win32") {
  environment.TMPDIR = "/tmp";
  environment.TMP = "/tmp";
  environment.TEMP = "/tmp";
}
const localLibraries = path.resolve(
  process.cwd(),
  "../../.runtime/playwright-deps/usr/lib/x86_64-linux-gnu",
);
if (existsSync(localLibraries)) {
  environment.LD_LIBRARY_PATH = [localLibraries, environment.LD_LIBRARY_PATH]
    .filter(Boolean)
    .join(":");
}

const cli = path.join(process.cwd(), "node_modules/@playwright/test/cli.js");
const result = spawnSync(
  process.execPath,
  [cli, "test", ...process.argv.slice(2)],
  {
    env: environment,
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
