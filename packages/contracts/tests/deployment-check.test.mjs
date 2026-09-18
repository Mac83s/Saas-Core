import assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  assertBillingConfiguration,
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
    "shared.sites",
    "shared.media",
    "shared.profiles",
    "shared.notifications",
    "shared.booking",
    "shared.seo",
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

test("shared.billing wymaga dokładnie trzech unikalnych kluczy planu", () => {
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
    /dokładnie 3 unikalnych billing\.planKeys/,
  );
  assert.doesNotThrow(() =>
    assertBillingConfiguration({
      id: "valid-billing",
      modules: ["shared.billing"],
      billing: { planKeys: ["profile", "starter", "pro"] },
    }),
  );
  assert.throws(
    () =>
      assertBillingConfiguration({
        id: "too-many-plans",
        modules: ["shared.billing"],
        billing: { planKeys: ["profile", "starter", "pro", "enterprise"] },
      }),
    /dokładnie 3 unikalnych billing\.planKeys/,
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

  const own = await singleModuleRoot({
    roleGrants: { owner: ["health.read"] },
    appointmentKinds: { "health.visit": "Wizyta" },
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
