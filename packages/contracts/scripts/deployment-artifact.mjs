/**
 * The fingerprint of one composed product.
 *
 * A deployment is a profile plus the descriptors of the modules it names, and
 * four processes have to agree on it: backend, worker, scheduler and frontend.
 * They are built as separate images, so nothing stops a frontend built from one
 * tree meeting a backend built from another — the panel would then show a menu
 * for a module whose routes answer 404, which looks like a bug in the feature
 * rather than a mismatched deploy.
 *
 * The artifact is that agreement written down: what the product is made of, and
 * one hash over it. It is committed so a change to any module contract shows up
 * as a diff in every profile that uses it, which is the review nobody gets from
 * a hash computed at build time and thrown away.
 */

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { repositoryRoot, validateDeployment } from "./deployment-check.mjs";

export const ARTIFACT_FILENAME = "module-artifact.json";

/** Key order must not change a hash, so it is fixed rather than incidental. */
const canonical = (value) => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value ?? null);
};

export function buildArtifact(profile, modules, descriptorsById) {
  const body = {
    schemaVersion: profile.schemaVersion,
    deployment: profile.id,
    product: profile.product,
    features: profile.features,
    // In composed order: two profiles with the same modules in a different
    // order are the same product, but a process installs them in this one.
    modules: modules.map((id) => {
      const descriptor = descriptorsById.get(id);
      return {
        id: descriptor.id,
        version: descriptor.version,
        layer: descriptor.layer,
        dependsOn: [...descriptor.dependsOn],
        backend: descriptor.backend,
        frontend: descriptor.frontend,
      };
    }),
  };
  const digest = createHash("sha256")
    .update(canonical(body), "utf8")
    .digest("hex");
  return { profileHash: `sha256:${digest}`, ...body };
}

export async function artifactFor(profileName, root = repositoryRoot) {
  const { profile, modules, descriptorsById } = await validateDeployment(
    profileName,
    root,
  );
  return buildArtifact(profile, modules, descriptorsById);
}

export const artifactPath = (profileName, root = repositoryRoot) =>
  path.join(root, "deployments", profileName, ARTIFACT_FILENAME);

const serialize = (artifact) => `${JSON.stringify(artifact, null, 2)}\n`;

async function main() {
  const profileFlag = process.argv.indexOf("--profile");
  const names =
    profileFlag >= 0
      ? [process.argv[profileFlag + 1]]
      : ["core-only", "business", "vps-dev", "hoofcare"];
  const check = process.argv.includes("--check");

  for (const name of names) {
    if (!name) {
      console.error(
        "Użycie: deployment-artifact.mjs [--profile <nazwa>] [--check]",
      );
      process.exitCode = 2;
      return;
    }
    const artifact = await artifactFor(name);
    const target = artifactPath(name);
    if (check) {
      let committed = "";
      try {
        committed = await readFile(target, "utf8");
      } catch {
        throw new Error(
          `Brak artefaktu ${path.relative(repositoryRoot, target)}: uruchom \`pnpm deployment:artifact\``,
        );
      }
      if (committed.replaceAll("\r\n", "\n") !== serialize(artifact)) {
        throw new Error(
          `Artefakt ${name} jest nieaktualny: uruchom \`pnpm deployment:artifact\``,
        );
      }
      console.log(`Artefakt ${name} aktualny: ${artifact.profileHash}`);
    } else {
      await writeFile(target, serialize(artifact), { encoding: "utf8" });
      console.log(
        `Zapisano ${path.relative(repositoryRoot, target)}: ${artifact.profileHash}`,
      );
    }
  }
}

if (
  process.argv[1] &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1])
) {
  try {
    await main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
