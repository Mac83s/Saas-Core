import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { repositoryRoot, validateDeployment } from "./deployment-check.mjs";

const profileFlag = process.argv.indexOf("--profile");
const profileName =
  profileFlag >= 0 ? process.argv[profileFlag + 1] : undefined;

export function toPublicDeployment(profile, modules) {
  return {
    schemaVersion: profile.schemaVersion,
    id: profile.id,
    product: profile.product,
    modules,
    features: profile.features,
  };
}

async function main() {
  if (!profileName) {
    console.error("Użycie: deployment-render.mjs --profile <nazwa>");
    process.exitCode = 2;
    return;
  }
  try {
    const { profile, modules } = await validateDeployment(profileName);
    const targetDirectory = path.join(
      repositoryRoot,
      "apps/frontend/src/generated",
    );
    const targetPath = path.join(targetDirectory, "deployment.ts");
    const publicProfile = toPublicDeployment(profile, modules);
    const source = [
      "// Wygenerowano przez pnpm deployment:render. Nie edytuj ręcznie.",
      `export const deployment = ${JSON.stringify(publicProfile, null, 2)} as const`,
      "",
    ].join("\n");

    await mkdir(targetDirectory, { recursive: true });
    await writeFile(targetPath, source, { encoding: "utf8" });
    console.log(`Zapisano ${path.relative(repositoryRoot, targetPath)}`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

if (
  process.argv[1] &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1])
) {
  await main();
}
