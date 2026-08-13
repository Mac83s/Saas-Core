import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
export const repositoryRoot = path.resolve(scriptDirectory, "../../..");

const parseJson = async (filePath) =>
  JSON.parse(await readFile(filePath, { encoding: "utf8" }));

const createValidator = (schema) => {
  const ajv = new Ajv2020({
    allErrors: true,
    strict: true,
    allowUnionTypes: true,
  });
  addFormats(ajv);
  return ajv.compile(schema);
};

const formatErrors = (errors = []) =>
  errors
    .map((error) => `${error.instancePath || "/"} ${error.message}`)
    .join("; ");

const assertNoSecretKeys = (value, location = "/") => {
  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      assertNoSecretKeys(item, `${location}${index}/`),
    );
    return;
  }
  if (!value || typeof value !== "object") return;

  for (const [key, child] of Object.entries(value)) {
    if (/(password|secret|token|private.?key|api.?key)/i.test(key)) {
      throw new Error(
        `Profil zawiera zabroniony klucz sekretu: ${location}${key}`,
      );
    }
    assertNoSecretKeys(child, `${location}${key}/`);
  }
};

export const assertBillingConfiguration = (
  profile,
  profileName = profile.id,
) => {
  if (!profile.modules.includes("shared.billing")) return;
  const planKeys = profile.billing?.planKeys;
  if (
    !Array.isArray(planKeys) ||
    planKeys.length !== 3 ||
    new Set(planKeys).size !== planKeys.length
  ) {
    throw new Error(
      `Profil ${profileName}: shared.billing wymaga dokładnie 3 unikalnych billing.planKeys`,
    );
  }
};

const loadDescriptors = async (root) => {
  const directory = path.join(root, "packages/contracts/modules");
  const files = (await readdir(directory))
    .filter((file) => file.endsWith(".json"))
    .sort();
  return Promise.all(
    files.map((file) => parseJson(path.join(directory, file))),
  );
};

const sortModules = (selected, descriptorsById) => {
  const visiting = new Set();
  const visited = new Set();
  const ordered = [];

  const visit = (moduleId) => {
    if (visiting.has(moduleId)) {
      throw new Error(`Wykryto cykl zależności przy module ${moduleId}`);
    }
    if (visited.has(moduleId)) return;

    visiting.add(moduleId);
    const descriptor = descriptorsById.get(moduleId);
    for (const dependency of descriptor.dependsOn) visit(dependency);
    visiting.delete(moduleId);
    visited.add(moduleId);
    ordered.push(moduleId);
  };

  for (const moduleId of selected) visit(moduleId);
  return ordered;
};

export async function validateDeployment(profileName, root = repositoryRoot) {
  if (!/^[a-z][a-z0-9-]*$/.test(profileName)) {
    throw new Error(`Nieprawidłowa nazwa profilu: ${profileName}`);
  }

  const deploymentSchema = await parseJson(
    path.join(root, "packages/contracts/deployment.schema.json"),
  );
  const moduleSchema = await parseJson(
    path.join(root, "packages/contracts/module.schema.json"),
  );
  const profilePath = path.join(
    root,
    "deployments",
    profileName,
    "deployment.json",
  );
  const profile = await parseJson(profilePath);
  const descriptors = await loadDescriptors(root);

  const validateProfile = createValidator(deploymentSchema);
  if (!validateProfile(profile)) {
    throw new Error(
      `Profil ${profileName}: ${formatErrors(validateProfile.errors)}`,
    );
  }
  assertNoSecretKeys(profile);
  if (profile.id !== profileName) {
    throw new Error(
      `Id profilu ${profile.id} nie zgadza się z katalogiem ${profileName}`,
    );
  }
  if (
    !profile.product.supportedLocales.includes(profile.product.defaultLocale)
  ) {
    throw new Error("Domyślne locale musi należeć do supportedLocales");
  }
  assertBillingConfiguration(profile, profileName);

  const validateModule = createValidator(moduleSchema);
  const descriptorsById = new Map();
  for (const descriptor of descriptors) {
    if (!validateModule(descriptor)) {
      throw new Error(
        `Moduł ${descriptor.id ?? "<unknown>"}: ${formatErrors(validateModule.errors)}`,
      );
    }
    if (descriptor.id.split(".")[0] !== descriptor.layer) {
      throw new Error(
        `Warstwa modułu ${descriptor.id} nie zgadza się z jego identyfikatorem`,
      );
    }
    if (descriptorsById.has(descriptor.id)) {
      throw new Error(`Powielony deskryptor modułu ${descriptor.id}`);
    }
    descriptorsById.set(descriptor.id, descriptor);
  }

  const selected = new Set(profile.modules);
  const layerRank = { core: 0, shared: 1, vertical: 2, config: 3 };
  for (const moduleId of selected) {
    const descriptor = descriptorsById.get(moduleId);
    if (!descriptor) throw new Error(`Nieznany moduł ${moduleId}`);

    for (const dependency of descriptor.dependsOn) {
      const dependencyDescriptor = descriptorsById.get(dependency);
      if (!dependencyDescriptor) {
        throw new Error(
          `Moduł ${moduleId} zależy od nieznanego modułu ${dependency}`,
        );
      }
      if (!selected.has(dependency)) {
        throw new Error(
          `Profil ${profileName}: ${moduleId} wymaga modułu ${dependency}`,
        );
      }
      if (layerRank[dependencyDescriptor.layer] > layerRank[descriptor.layer]) {
        throw new Error(
          `Niedozwolony kierunek zależności ${moduleId} -> ${dependency}`,
        );
      }
    }
  }

  return { profile, modules: sortModules(profile.modules, descriptorsById) };
}

const isMain =
  process.argv[1] &&
  pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  const profileFlag = process.argv.indexOf("--profile");
  const profileName =
    profileFlag >= 0 ? process.argv[profileFlag + 1] : undefined;
  if (!profileName) {
    console.error("Użycie: deployment-check.mjs --profile <nazwa>");
    process.exitCode = 2;
  } else {
    try {
      const result = await validateDeployment(profileName);
      console.log(
        `Profil ${profileName} poprawny: ${result.modules.join(" -> ")}`,
      );
    } catch (error) {
      console.error(error instanceof Error ? error.message : error);
      process.exitCode = 1;
    }
  }
}
