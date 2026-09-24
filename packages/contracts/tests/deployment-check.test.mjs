import assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  assertBillingConfiguration,
  effectiveOrganizationTypes,
  repositoryRoot,
  validateDeployment,
} from "../scripts/deployment-check.mjs";
import { toPublicDeployment } from "../scripts/deployment-render.mjs";

test("profil core-only jest poprawny i posortowany zależnościami", async () => {
  const result = await validateDeployment("core-only");
  assert.deepEqual(result.modules, [
    "core.health",
    "core.identity",
    "core.organizations",
  ]);
  assert.equal(result.profile.billing, undefined);
});

test("profil business składa wszystkie moduły Shared bez verticala", async () => {
  const result = await validateDeployment("business");
  assert.deepEqual(result.modules, [
    "core.health",
    "core.identity",
    "core.organizations",
    "shared.billing",
    "shared.notifications",
    "shared.sites",
    "shared.media",
    "shared.profiles",
    "shared.booking",
    "shared.seo",
    "shared.inventory",
  ]);
  assert.ok(
    result.modules.every((id) => /^(core|shared)\./.test(id)),
    "profil generyczny nie ma warstwy vertical ani config",
  );
  assert.deepEqual(result.profile.billing.planKeys, [
    "profile",
    "starter",
    "pro",
  ]);
});

test("deskryptor aplikacji, której nie ma w kodzie, jest odrzucany", async () => {
  // A catalog that lies passes schema and graph checks and fails only at boot.
  // Build a repository root with one phantom module and make sure the check
  // refuses it before anything gets built.
  const root = await mkdtemp(path.join(tmpdir(), "saas-core-catalog-"));
  const contracts = path.join(root, "packages/contracts");
  await mkdir(path.join(contracts, "modules"), { recursive: true });
  await mkdir(path.join(root, "deployments/ghost"), { recursive: true });
  // The backend tree has to exist for the check to run at all — its absence
  // is what lets the frontend image build without the backend source.
  await mkdir(path.join(root, "apps/backend/src"), { recursive: true });
  for (const file of ["deployment.schema.json", "module.schema.json"]) {
    await cp(
      path.join(repositoryRoot, "packages/contracts", file),
      path.join(contracts, file),
    );
  }
  await writeFile(
    path.join(contracts, "modules/core.ghost.json"),
    JSON.stringify({
      id: "core.ghost",
      layer: "core",
      version: 1,
      dependsOn: [],
      backend: {
        djangoApp: "saas_core.modules.core.ghost",
        urlPrefix: null,
        permissions: [],
        entitlements: [],
        eventSchemas: [],
        publicTables: [],
        platformTables: [],
      },
      frontend: { routes: [], navigation: [], translationNamespaces: [] },
    }),
  );
  await writeFile(
    path.join(root, "deployments/ghost/deployment.json"),
    JSON.stringify({
      schemaVersion: 1,
      id: "ghost",
      product: {
        name: "Ghost",
        defaultLocale: "pl",
        supportedLocales: ["pl"],
        platformDomain: "ghost.localhost",
      },
      modules: ["core.ghost"],
      features: {},
    }),
  );

  await assert.rejects(
    validateDeployment("ghost", root),
    /core\.ghost deklaruje backend\.djangoApp saas_core\.modules\.core\.ghost, którego nie ma/,
  );
});

test("bez drzewa backendu sprawdzenie aplikacji jest pomijane", async () => {
  // The frontend image copies only apps/frontend, deployments and packages, so
  // the render step inside that build has nothing to look at. Skipping there is
  // deliberate: the same guarantee is asserted by the backend's own test.
  const root = await mkdtemp(path.join(tmpdir(), "saas-core-nobackend-"));
  const contracts = path.join(root, "packages/contracts");
  await mkdir(path.join(contracts, "modules"), { recursive: true });
  await mkdir(path.join(root, "deployments/ghost"), { recursive: true });
  for (const file of ["deployment.schema.json", "module.schema.json"]) {
    await cp(
      path.join(repositoryRoot, "packages/contracts", file),
      path.join(contracts, file),
    );
  }
  await writeFile(
    path.join(contracts, "modules/core.ghost.json"),
    JSON.stringify({
      id: "core.ghost",
      layer: "core",
      version: 1,
      dependsOn: [],
      backend: {
        djangoApp: "saas_core.modules.core.ghost",
        urlPrefix: null,
        permissions: [],
        entitlements: [],
        eventSchemas: [],
        publicTables: [],
        platformTables: [],
      },
      frontend: { routes: [], navigation: [], translationNamespaces: [] },
    }),
  );
  await writeFile(
    path.join(root, "deployments/ghost/deployment.json"),
    JSON.stringify({
      schemaVersion: 1,
      id: "ghost",
      product: {
        name: "Ghost",
        defaultLocale: "pl",
        supportedLocales: ["pl"],
        platformDomain: "ghost.localhost",
      },
      modules: ["core.ghost"],
      features: {},
    }),
  );

  const result = await validateDeployment("ghost", root);
  assert.deepEqual(result.modules, ["core.ghost"]);
});

test("moduł nie może zadeklarować cudzej tabeli jako publicznej", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "saas-core-public-tables-"));
  const contracts = path.join(root, "packages/contracts");
  await mkdir(path.join(contracts, "modules"), { recursive: true });
  await mkdir(path.join(root, "deployments/only-health"), { recursive: true });
  for (const file of ["deployment.schema.json", "module.schema.json"]) {
    await cp(
      path.join(repositoryRoot, "packages/contracts", file),
      path.join(contracts, file),
    );
  }
  // Give the temporary root a health app, so the existence check passes and
  // only the ownership of the declared table can fail.
  const healthApp = path.join(
    root,
    "apps/backend/src/saas_core/modules/core/health",
  );
  await mkdir(healthApp, { recursive: true });

  await writeFile(path.join(healthApp, "apps.py"), "");
  await writeFile(
    path.join(contracts, "modules/core.health.json"),
    JSON.stringify({
      id: "core.health",
      layer: "core",
      version: 1,
      dependsOn: [],
      backend: {
        djangoApp: "saas_core.modules.core.health",
        urlPrefix: null,
        permissions: [],
        entitlements: [],
        eventSchemas: [],
        publicTables: ["sites_domain"],
        platformTables: [],
      },
      frontend: { routes: [], navigation: [], translationNamespaces: [] },
    }),
  );
  await writeFile(
    path.join(root, "deployments/only-health/deployment.json"),
    JSON.stringify({
      schemaVersion: 1,
      id: "only-health",
      product: {
        name: "Only health",
        defaultLocale: "pl",
        supportedLocales: ["pl"],
        platformDomain: "health.localhost",
      },
      modules: ["core.health"],
      features: {},
    }),
  );

  await assert.rejects(
    validateDeployment("only-health", root),
    /core\.health deklaruje publiczną tabelę sites_domain, która nie należy do aplikacji health/,
  );
});

test("profil business deklaruje tabele publiczne tylko w shared.sites", async () => {
  const result = await validateDeployment("business");
  assert.ok(result.modules.includes("shared.sites"));
});

test("shared.billing wymaga od jednego do sześciu unikalnych kluczy planu", () => {
  assert.throws(
    () =>
      assertBillingConfiguration(
        {
          id: "invalid-billing",
          modules: ["shared.billing"],
          billing: { planKeys: ["profile", "profile"] },
        },
        "invalid-billing",
      ),
    /od 1 do 6 unikalnych billing\.planKeys/,
  );
  // Produkt z dwoma typami organizacji sprzedaje więcej niż trzy plany:
  // gospodarstwo ma darmowy i płatny obok planów firmy.
  assert.doesNotThrow(() =>
    assertBillingConfiguration({
      id: "valid-billing",
      modules: ["shared.billing"],
      billing: {
        planKeys: ["profile", "starter", "pro", "farm_free", "farm_plus"],
      },
    }),
  );
  assert.throws(
    () =>
      assertBillingConfiguration({
        id: "no-plans",
        modules: ["shared.billing"],
        billing: { planKeys: [] },
      }),
    /od 1 do 6 unikalnych billing\.planKeys/,
  );
  assert.throws(
    () =>
      assertBillingConfiguration({
        id: "too-many-plans",
        modules: ["shared.billing"],
        billing: {
          planKeys: ["a", "b", "c", "d", "e", "f", "g"],
        },
      }),
    /od 1 do 6 unikalnych billing\.planKeys/,
  );
});

test("nazwa profilu nie może uciec poza katalog deployments", async () => {
  await assert.rejects(
    validateDeployment("../business"),
    /Nieprawidłowa nazwa profilu/,
  );
  // Parked profiles live outside the catalog on purpose and are not checkable.
  await assert.rejects(
    validateDeployment("_planned/example"),
    /Nieprawidłowa nazwa profilu/,
  );
});

test("profil publiczny nie przenosi sekretów ani nieznanych pól", () => {
  const publicProfile = toPublicDeployment(
    {
      schemaVersion: 1,
      id: "test",
      product: { name: "Test" },
      features: {},
      apiToken: "sekret",
      databasePassword: "sekret",
    },
    ["core.identity"],
    "a".repeat(64),
  );

  assert.deepEqual(Object.keys(publicProfile).sort(), [
    "features",
    "id",
    "modules",
    "organizationTypes",
    "product",
    "profileHash",
    "schemaVersion",
  ]);
  assert.equal(publicProfile.profileHash, "a".repeat(64));
  assert.doesNotMatch(JSON.stringify(publicProfile), /sekret/);
});

// One module, `core.health`, with the backend section under test.
const singleModuleRoot = async (backend) => {
  const root = await mkdtemp(path.join(tmpdir(), "saas-core-extension-"));
  const contracts = path.join(root, "packages/contracts");
  await mkdir(path.join(contracts, "modules"), { recursive: true });
  await mkdir(path.join(root, "deployments/only-health"), { recursive: true });
  for (const file of ["deployment.schema.json", "module.schema.json"]) {
    await cp(
      path.join(repositoryRoot, "packages/contracts", file),
      path.join(contracts, file),
    );
  }
  const healthApp = path.join(
    root,
    "apps/backend/src/saas_core/modules/core/health",
  );
  await mkdir(healthApp, { recursive: true });
  await writeFile(path.join(healthApp, "apps.py"), "");
  await writeFile(
    path.join(contracts, "modules/core.health.json"),
    JSON.stringify({
      id: "core.health",
      layer: "core",
      version: 1,
      dependsOn: [],
      backend: {
        djangoApp: "saas_core.modules.core.health",
        urlPrefix: null,
        permissions: ["health.read"],
        entitlements: [],
        eventSchemas: [],
        publicTables: [],
        platformTables: [],
        ...backend,
      },
      frontend: { routes: [], navigation: [], translationNamespaces: [] },
    }),
  );
  await writeFile(
    path.join(root, "deployments/only-health/deployment.json"),
    JSON.stringify({
      schemaVersion: 1,
      id: "only-health",
      product: {
        name: "Only health",
        defaultLocale: "pl",
        supportedLocales: ["pl"],
        platformDomain: "health.localhost",
      },
      modules: ["core.health"],
      features: {},
    }),
  );
  return root;
};

test("moduł nadaje rolom tylko własne uprawnienia i montuje tylko własny kod (ADR-049)", async () => {
  await assert.rejects(
    validateDeployment(
      "only-health",
      await singleModuleRoot({ roleGrants: { owner: ["billing.manage"] } }),
    ),
    /nadaje roli owner uprawnienie billing\.manage, którego nie deklaruje/,
  );
  await assert.rejects(
    validateDeployment(
      "only-health",
      await singleModuleRoot({
        middleware: ["saas_core.modules.shared.sites.middleware.Foreign"],
      }),
    ),
    /nie należy do saas_core\.modules\.core\.health/,
  );
  await assert.rejects(
    validateDeployment(
      "only-health",
      await singleModuleRoot({
        beatSchedule: {
          foreign: {
            task: "saas_core.modules.shared.seo.tasks.x",
            schedule: 60,
          },
        },
      }),
    ),
    /nie należy do saas_core\.modules\.core\.health/,
  );

  // Own material only for a visit kind the module itself adds (ADR-055).
  await assert.rejects(
    validateDeployment(
      "only-health",
      await singleModuleRoot({
        appointmentKinds: { "health.visit": "Wizyta" },
        appointmentKindsWithOwnMaterials: ["health.other"],
      }),
    ),
    /własne materiały dla nieznanego typu wizyty health\.other/,
  );

  const own = await singleModuleRoot({
    roleGrants: { owner: ["health.read"] },
    appointmentKinds: { "health.visit": "Wizyta" },
    appointmentKindsWithOwnMaterials: ["health.visit"],
    middleware: ["saas_core.modules.core.health.middleware.Own"],
    beatSchedule: {
      "health-own": {
        task: "saas_core.modules.core.health.tasks.own",
        schedule: 60,
      },
    },
  });
  const result = await validateDeployment("only-health", own);
  assert.deepEqual(result.modules, ["core.health"]);
});

// A profile with shared.billing and two organization types, for ADR-050.
const typedProfileRoot = async (organizationTypes) => {
  const root = await mkdtemp(path.join(tmpdir(), "saas-core-org-types-"));
  await cp(
    path.join(repositoryRoot, "packages/contracts"),
    path.join(root, "packages/contracts"),
    {
      recursive: true,
      filter: (source) => !source.includes("node_modules"),
    },
  );
  await mkdir(path.join(root, "deployments/typed"), { recursive: true });
  const business = JSON.parse(
    await readFile(
      path.join(repositoryRoot, "deployments/business/deployment.json"),
      "utf8",
    ),
  );
  await writeFile(
    path.join(root, "deployments/typed/deployment.json"),
    JSON.stringify({
      ...business,
      id: "typed",
      organizationTypes,
    }),
  );
  return root;
};

test("typy organizacji używają tylko modułów i planów profilu (ADR-050)", async () => {
  const company = {
    key: "company",
    label: { pl: "Firma", en: "Company" },
    modules: ["shared.billing", "shared.booking"],
    planKeys: ["profile"],
    selfSignup: true,
  };
  const ok = await validateDeployment(
    "typed",
    await typedProfileRoot([company]),
  );
  assert.ok(ok.modules.includes("shared.booking"));

  await assert.rejects(
    validateDeployment(
      "typed",
      await typedProfileRoot([{ ...company, modules: ["vertical.nothing"] }]),
    ),
    /typ company używa modułu vertical\.nothing, którego profil nie składa/,
  );
  await assert.rejects(
    validateDeployment(
      "typed",
      await typedProfileRoot([{ ...company, planKeys: ["gold"] }]),
    ),
    /typ company oferuje plan gold spoza billing\.planKeys/,
  );
  await assert.rejects(
    validateDeployment("typed", await typedProfileRoot([company, company])),
    /powielony typ organizacji company/,
  );
});

test("profil bez typów dostaje jeden typ business ze wszystkim (ADR-050)", () => {
  const [only] = effectiveOrganizationTypes(
    { billing: { planKeys: ["a", "b", "c"] } },
    ["core.identity", "shared.billing", "vertical.x"],
  );
  assert.equal(only.key, "business");
  assert.deepEqual(only.modules, ["shared.billing", "vertical.x"]);
  assert.deepEqual(only.planKeys, ["a", "b", "c"]);
  assert.equal(only.selfSignup, true);
});

test("role typu: owner i admin, uprawnienia modułów typu, owner z całym rdzeniem (ADR-050)", async () => {
  const core = [
    "organization.read",
    "organization.members.manage",
    "organization.members.read",
    "organization.members.manage_limited",
    "organization.settings.manage",
    "organization.ownership.transfer",
    "organization.archive",
  ];
  const type = (roles) => ({
    key: "company",
    label: { pl: "Firma", en: "Company" },
    modules: ["shared.billing", "shared.booking"],
    planKeys: ["profile"],
    selfSignup: true,
    roles,
  });
  const role = (key, permissions) => ({
    key,
    label: { pl: key, en: key },
    permissions,
  });

  const ok = await typedProfileRoot([
    type([
      role("owner", [...core, "booking.appointment.manage"]),
      role("admin", ["organization.read"]),
    ]),
  ]);
  await validateDeployment("typed", ok);

  await assert.rejects(
    validateDeployment(
      "typed",
      await typedProfileRoot([type([role("owner", core), role("worker", [])])]),
    ),
    /nie ma roli admin/,
  );
  await assert.rejects(
    validateDeployment(
      "typed",
      await typedProfileRoot([
        type([role("owner", [...core, "site.publish"]), role("admin", [])]),
      ]),
    ),
    /company\.owner nadaje site\.publish/,
  );
  await assert.rejects(
    validateDeployment(
      "typed",
      await typedProfileRoot([
        type([role("owner", ["organization.read"]), role("admin", [])]),
      ]),
    ),
    /company\.owner musi mieć organization\.members\.manage/,
  );
});

test("magazyn typu: kategorie i pozycje standardowe produktu (ADR-055)", async () => {
  const block = { key: "block", label: { pl: "Klocek", en: "Block" } };
  const item = {
    key: "block",
    name: { pl: "Klocek", en: "Block" },
    category: "block",
    unit: "piece",
  };
  const company = {
    key: "company",
    label: { pl: "Firma", en: "Company" },
    modules: ["shared.billing", "shared.inventory"],
    planKeys: ["profile"],
    selfSignup: true,
    inventory: { categories: [block], defaultItems: [item] },
  };
  const result = await validateDeployment(
    "typed",
    await typedProfileRoot([company]),
  );
  assert.deepEqual(
    effectiveOrganizationTypes(result.profile, result.modules)[0].inventory,
    { categories: [block], defaultItems: [item] },
  );
  // Without the field nothing is written, so existing artifacts keep their hash.
  const { inventory: _omitted, ...plain } = company;
  assert.equal(
    "inventory" in
      effectiveOrganizationTypes({ organizationTypes: [plain] }, [])[0],
    false,
  );
  for (const [patch, pattern] of [
    [{ modules: ["shared.billing"] }, /magazyn bez shared.inventory/],
    [
      { inventory: { categories: [block, block], defaultItems: [] } },
      /powtarza klucz kategorii magazynu/,
    ],
    [
      { inventory: { categories: [block], defaultItems: [item, item] } },
      /powtarza klucz pozycji standardowej/,
    ],
    [
      {
        inventory: {
          categories: [block],
          defaultItems: [{ ...item, category: "drug" }],
        },
      },
      /kategorię drug/,
    ],
    [
      {
        inventory: {
          categories: [block],
          defaultItems: [{ ...item, unit: "box" }],
        },
      },
      /inventory/,
    ],
  ]) {
    await assert.rejects(
      validateDeployment(
        "typed",
        await typedProfileRoot([{ ...company, ...patch }]),
      ),
      pattern,
    );
  }
});

test("kategorie katalogu należą do typu i wymagają modułu profili", async () => {
  const category = {
    key: "specialists",
    label: { pl: "Specjaliści", en: "Specialists" },
  };
  const company = {
    key: "company",
    label: { pl: "Firma", en: "Company" },
    modules: ["shared.profiles"],
    planKeys: ["profile"],
    selfSignup: true,
    catalogCategories: [category],
  };
  const result = await validateDeployment(
    "typed",
    await typedProfileRoot([company]),
  );
  assert.deepEqual(
    effectiveOrganizationTypes(result.profile, result.modules)[0]
      .catalogCategories,
    [category],
  );
  assert.deepEqual(
    toPublicDeployment(result.profile, result.modules, "a".repeat(64))
      .organizationTypes[0].catalogCategories,
    [category],
  );
  const empty = { ...company, catalogCategories: [] };
  assert.deepEqual(
    effectiveOrganizationTypes({ organizationTypes: [empty] }, [])[0]
      .catalogCategories,
    [],
  );
  for (const [patch, pattern] of [
    [{ catalogCategories: [category, category] }, /powtarza klucz kategorii/],
    [{ modules: [] }, /kategorie bez shared.profiles/],
    [
      { catalogCategories: [{ ...category, key: "../escape" }] },
      /catalogCategories/,
    ],
    [
      { catalogCategories: [{ ...category, key: "x".repeat(65) }] },
      /catalogCategories/,
    ],
    [
      { catalogCategories: [{ ...category, label: { pl: "Specjaliści" } }] },
      /catalogCategories/,
    ],
  ]) {
    await assert.rejects(
      validateDeployment(
        "typed",
        await typedProfileRoot([{ ...company, ...patch }]),
      ),
      pattern,
    );
  }
});
