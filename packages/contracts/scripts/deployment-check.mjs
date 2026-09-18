import { access, readFile, readdir } from "node:fs/promises";
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

// The catalog describes code that exists. A descriptor for an app nobody has
// written passes schema and graph checks and only fails at boot, in the image.
//
// This can only be checked where the backend source is present. The frontend
// image deliberately copies just apps/frontend, deployments and packages, so
// inside that build there is nothing to look at — and a frontend build must
// not depend on the backend tree. Where the source is missing the check steps
// aside and says so; the same guarantee is asserted from the other direction
// by the backend's tests/test_module_catalog.py.
const backendSourcePresent = async (root) => {
  try {
    await access(path.join(root, "apps/backend/src"));
    return true;
  } catch {
    return false;
  }
};

const assertDjangoAppExists = async (descriptor, root) => {
  const djangoApp = descriptor.backend.djangoApp;
  if (!djangoApp) return;
  const appConfig = path.join(
    root,
    "apps/backend/src",
    ...djangoApp.split("."),
    "apps.py",
  );
  try {
    await access(appConfig);
  } catch {
    throw new Error(
      `Moduł ${descriptor.id} deklaruje backend.djangoApp ${djangoApp}, którego nie ma w apps/backend/src`,
    );
  }
};

// ADR-039 and ADR-041: a module may only open its own tables, and only in a
// regime it names. The backend test checks the live schema; this keeps a
// descriptor from declaring somebody else's table on paper.
const assertDeclaredTablesBelongToModule = (descriptor) => {
  const djangoApp = descriptor.backend.djangoApp;
  const declared = [
    ["publiczną", descriptor.backend.publicTables],
    ["platformową", descriptor.backend.platformTables],
  ];
  for (const [regime, tables] of declared) {
    if (tables.length === 0) continue;
    if (!djangoApp) {
      throw new Error(
        `Moduł ${descriptor.id} deklaruje tabele bez backend.djangoApp`,
      );
    }
    const appLabel = djangoApp.split(".").at(-1);
    for (const table of tables) {
      if (!table.startsWith(`${appLabel}_`)) {
        throw new Error(
          `Moduł ${descriptor.id} deklaruje ${regime} tabelę ${table}, która nie należy do aplikacji ${appLabel}`,
        );
      }
    }
  }
  const overlap = (descriptor.backend.publicTables ?? []).filter((table) =>
    (descriptor.backend.platformTables ?? []).includes(table),
  );
  if (overlap.length > 0) {
    throw new Error(
      `Moduł ${descriptor.id} deklaruje te same tabele jako publiczne i platformowe: ${overlap.join(", ")}`,
    );
  }
};

// ADR-049: a module may grant roles only the permissions it declares, so a
// product cannot hand out core's or another module's permissions on the side.
const assertGrantsAreOwnPermissions = (descriptor) => {
  const own = new Set(descriptor.backend.permissions);
  for (const [role, grants] of Object.entries(
    descriptor.backend.roleGrants ?? {},
  )) {
    for (const permission of grants) {
      if (!own.has(permission)) {
        throw new Error(
          `Moduł ${descriptor.id} nadaje roli ${role} uprawnienie ${permission}, którego nie deklaruje`,
        );
      }
    }
  }
};

// ADR-049: middleware and scheduled tasks a module declares must be its own
// code, so a descriptor cannot mount somebody else's.
const assertDeclaredCodeIsOwn = (descriptor) => {
  const own = descriptor.backend.djangoApp;
  const paths = [
    ...(descriptor.backend.middleware ?? []),
    ...Object.values(descriptor.backend.beatSchedule ?? {}).map(
      (entry) => entry.task,
    ),
  ];
  for (const dotted of paths) {
    if (!own || !dotted.startsWith(`${own}.`)) {
      throw new Error(
        `Moduł ${descriptor.id} deklaruje ${dotted}, które nie należy do ${own ?? "żadnej aplikacji"}`,
      );
    }
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
  const checkDjangoApps = await backendSourcePresent(root);
  if (!checkDjangoApps) {
    console.warn(
      "Pomijam sprawdzenie istnienia Django apps: brak apps/backend/src w tym drzewie.",
    );
  }
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
    if (checkDjangoApps) {
      await assertDjangoAppExists(descriptor, root);
    }
    assertDeclaredTablesBelongToModule(descriptor);
    assertGrantsAreOwnPermissions(descriptor);
    assertDeclaredCodeIsOwn(descriptor);
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

  return {
    profile,
    modules: sortModules(profile.modules, descriptorsById),
    // The artifact needs the descriptors themselves, not only their names.
    descriptorsById,
  };
}

/**
 * This repository's main profile, from its `product.json` slot (ADR-049):
 * `business` in Saas-Core, the product's own in a product repository.
 */
export async function productProfile(root = repositoryRoot) {
  const raw = await readFile(path.join(root, "product.json"), "utf8");
  return JSON.parse(raw).profiles[0];
}

/**
 * Every profile this repository ships: `deployments/<name>/deployment.json`.
 * Parked ones (`_planned`) stay out. Discovered rather than listed, so a
 * product repository adds its profile without editing this file (ADR-049).
 */
export async function discoverProfiles(root = repositoryRoot) {
  const entries = await readdir(path.join(root, "deployments"), {
    withFileTypes: true,
  });
  const names = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith("_")) continue;
    const files = await readdir(path.join(root, "deployments", entry.name));
    if (files.includes("deployment.json")) names.push(entry.name);
  }
  return names.sort();
}

const isMain =
  process.argv[1] &&
  pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  const profileFlag = process.argv.indexOf("--profile");
  const profileNames = process.argv.includes("--all")
    ? await discoverProfiles()
    : [profileFlag >= 0 ? process.argv[profileFlag + 1] : undefined];
  if (!profileNames[0]) {
    console.error("Użycie: deployment-check.mjs --profile <nazwa> | --all");
    process.exitCode = 2;
  } else {
    for (const profileName of profileNames) {
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
}
