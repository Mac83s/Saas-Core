import assert from "node:assert/strict";
import { test } from "node:test";

import { validateDeployment } from "../scripts/deployment-check.mjs";
import { toPublicDeployment } from "../scripts/deployment-render.mjs";

test("profil core-only jest poprawny i posortowany zależnościami", async () => {
  const result = await validateDeployment("core-only");
  assert.deepEqual(result.modules, [
    "core.identity",
    "core.organizations",
    "core.audit",
  ]);
});

test("profil MedPlano zawiera vertical i warstwę konfiguracji na końcu", async () => {
  const result = await validateDeployment("medplano");
  assert.equal(result.modules.at(-1), "config.medplano");
  assert.ok(result.modules.includes("vertical.medical"));
});

test("nazwa profilu nie może uciec poza katalog deployments", async () => {
  await assert.rejects(
    validateDeployment("../medplano"),
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
  );

  assert.deepEqual(Object.keys(publicProfile).sort(), [
    "features",
    "id",
    "modules",
    "product",
    "schemaVersion",
  ]);
  assert.doesNotMatch(JSON.stringify(publicProfile), /sekret/);
});
