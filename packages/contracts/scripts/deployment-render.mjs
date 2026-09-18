import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  productProfile,
  repositoryRoot,
  validateDeployment,
} from "./deployment-check.mjs";
import { buildArtifact } from "./deployment-artifact.mjs";

const profileFlag = process.argv.indexOf("--profile");
const requestedProfile =
  profileFlag >= 0 ? process.argv[profileFlag + 1] : undefined;

export function toPublicDeployment(profile, modules, profileHash) {
  return {
    schemaVersion: profile.schemaVersion,
    id: profile.id,
    product: profile.product,
    modules,
    features: profile.features,
    // The fingerprint of the tree this bundle was built from. The panel
    // compares it with the backend's so a mismatched pair of images says so.
    profileHash,
  };
}

async function main() {
  // Without --profile: the repository's own product (product.json).
  const profileName = requestedProfile ?? (await productProfile());
  try {
    const { profile, modules, descriptorsById } =
      await validateDeployment(profileName);
    const { profileHash } = buildArtifact(profile, modules, descriptorsById);
    const targetDirectory = path.join(
      repositoryRoot,
      "apps/frontend/src/generated",
    );
    const targetPath = path.join(targetDirectory, "deployment.ts");
    const publicProfile = toPublicDeployment(profile, modules, profileHash);
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
