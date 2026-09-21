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
    planKeys.length < 1 ||
    planKeys.length > 6 ||
    new Set(planKeys).size !== planKeys.length
  ) {
    throw new Error(
      `Profil ${profileName}: shared.billing wymaga od 1 do 6 unikalnych billing.planKeys`,
    );
  }
};

/**
 * The organization types a profile composes (ADR-050), with the default a
 * profile without the section gets: one `business` type with every
 * non-core module and every plan. Computed once, here; the artifact carries
 * the result, so the backend and the frontend read the same list rather than
 * each re-deriving the default.
 */
export const effectiveOrganizationTypes = (profile, modules) => {
  if (profile.organizationTypes) {
    return profile.organizationTypes.map((type) => ({
      key: type.key,
      label: type.label,
      description: type.description ?? null,
      modules: [...type.modules],
      planKeys: [...(type.planKeys ?? profile.billing?.planKeys ?? [])],
      selfSignup: type.selfSignup,
      ...(type.catalogCategories !== undefined
        ? { catalogCategories: type.catalogCategories }
        : {}),
      roles: (type.roles ?? []).map((role) => ({
        key: role.key,
        label: role.label,
        permissions: [...role.permissions],
        limited: role.limited ?? false,
      })),
      serviceTemplates: (type.serviceTemplates ?? []).map((template) => ({
        key: template.key,
        label: template.label,
        durationMinutes: template.durationMinutes,
        appointmentKind: template.appointmentKind ?? null,
      })),
    }));
  }
  return [
    {
      key: "business",
      label: { pl: "Firma", en: "Business" },
      description: null,
      modules: modules.filter((id) => !id.startsWith("core.")),
      planKeys: [...(profile.billing?.planKeys ?? [])],
      selfSignup: true,
      roles: [],
      serviceTemplates: [],
    },
  ];
};

// Roles of a type (ADR-050): owner and admin must exist (ownership transfer
// demotes the owner to admin), every permission must be declared by a module
// the type composes, and the owner holds all of core.organizations'.
const assertTypeRoles = (
  type,
  profileName,
  descriptorsById,
  profileModules,
) => {
  if (!type.roles) return;
  const available = new Set(
    [
      ...profileModules.filter((id) => id.startsWith("core.")),
      ...type.modules,
    ].flatMap((id) => descriptorsById.get(id)?.backend.permissions ?? []),
  );
  const keys = new Set(type.roles.map((role) => role.key));
  for (const required of ["owner", "admin"]) {
    if (!keys.has(required)) {
      throw new Error(
        `Profil ${profileName}: typ ${type.key} nie ma roli ${required}`,
      );
    }
  }
  if (keys.size !== type.roles.length) {
    throw new Error(
      `Profil ${profileName}: typ ${type.key} powtarza klucz roli`,
    );
  }
  for (const role of type.roles) {
    for (const permission of role.permissions) {
      if (!available.has(permission)) {
        throw new Error(
          `Profil ${profileName}: rola ${type.key}.${role.key} nadaje ${permission}, którego nie deklaruje żaden moduł typu`,
        );
      }
    }
  }
  const owner = new Set(
    type.roles.find((role) => role.key === "owner").permissions,
  );
  for (const permission of descriptorsById.get("core.organizations")?.backend
    .permissions ?? []) {
    if (!owner.has(permission)) {
      throw new Error(
        `Profil ${profileName}: rola ${type.key}.owner musi mieć ${permission}`,
      );
    }
  }
};

const assertOrganizationTypes = (profile, profileName) => {
  const composed = new Set(profile.modules);
  const plans = new Set(profile.billing?.planKeys ?? []);
  const keys = new Set();
  for (const type of profile.organizationTypes ?? []) {
    if (keys.has(type.key)) {
      throw new Error(
        `Profil ${profileName}: powielony typ organizacji ${type.key}`,
      );
    }
    keys.add(type.key);
    const categories = type.catalogCategories ?? [];
    if (
      new Set(categories.map((category) => category.key)).size !==
      categories.length
    ) {
      throw new Error(
        `Profil ${profileName}: typ ${type.key} powtarza klucz kategorii katalogu`,
      );
    }
    if (categories.length && !type.modules.includes("shared.profiles")) {
      throw new Error(
        `Profil ${profileName}: typ ${type.key} deklaruje kategorie bez shared.profiles`,
      );
    }
    for (const moduleId of type.modules) {
      if (!composed.has(moduleId)) {
        throw new Error(
          `Profil ${profileName}: typ ${type.key} używa modułu ${moduleId}, którego profil nie składa`,
        );
      }
    }
    for (const plan of type.planKeys ?? []) {
      if (!plans.has(plan)) {
        throw new Error(
          `Profil ${profileName}: typ ${type.key} oferuje plan ${plan} spoza billing.planKeys`,
        );
      }
    }
    if (composed.has("shared.billing") && !type.planKeys) {
      throw new Error(
        `Profil ${profileName}: typ ${type.key} musi wskazać planKeys, bo profil składa shared.billing`,
      );
    }
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
  assertOrganizationTypes(profile, profileName);

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
  for (const type of profile.organizationTypes ?? []) {
    assertTypeRoles(type, profileName, descriptorsById, profile.modules);
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
