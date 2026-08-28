import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const contractDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../content-operations",
);

async function readJson(relativePath) {
  return JSON.parse(
    await readFile(path.join(contractDirectory, relativePath), "utf8"),
  );
}

async function changeSetValidator() {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  return ajv.compile(await readJson("content-change-set.v1.schema.json"));
}

async function blockDataAccepted(changeSet) {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  const blockDirectory = path.resolve(contractDirectory, "../site-blocks");
  for (const command of changeSet.commands) {
    if (command.block === undefined) continue;
    const schema = JSON.parse(
      await readFile(
        path.join(
          blockDirectory,
          `${command.block.type}.v${command.block.schema_version}.schema.json`,
        ),
        "utf8",
      ),
    );
    if (!ajv.compile(schema)(command.block.data)) return false;
  }
  return true;
}

test("the manifest names exactly the frozen vocabulary", async () => {
  const manifest = await readJson("manifest.json");

  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.contractVersion, 1);
  // A server never accepts a contract it does not implement, so the floor can
  // never rise above the ceiling.
  assert.ok(manifest.minimumContractVersion <= manifest.contractVersion);

  assert.deepEqual(manifest.surfaceKinds, ["site_page", "content_entry"]);
  assert.deepEqual(manifest.automationPolicies, [
    "manual",
    "proposed",
    "automated",
  ]);
  assert.deepEqual(manifest.grantModes, [
    "suggest_only",
    "draft_write",
    "publish_with_approval",
    "autonomous",
  ]);
  // ADR-035 §4: "limited" describes the bounds every autonomous grant carries,
  // not a fifth permission level. Carrying it as an alias would leave room for
  // an accidentally unlimited autonomy later.
  assert.ok(manifest.rejectedValues.includes("auto_publish_limited"));
  for (const rejected of manifest.rejectedValues) {
    assert.ok(!manifest.grantModes.includes(rejected));
  }
});

test("every command the manifest lists exists in the schema, and no others", async () => {
  const manifest = await readJson("manifest.json");
  const schema = await readJson("content-change-set.v1.schema.json");

  const declared = schema.$defs.command.oneOf.map((entry) => {
    const name = entry.$ref.replace("#/$defs/", "");
    return schema.$defs[name].properties.command.const;
  });
  assert.deepEqual([...declared].sort(), [...manifest.commands].sort());
});

test("accepted fixtures validate", async () => {
  const validate = await changeSetValidator();
  const index = await readJson("fixtures/index.json");
  const files = await readdir(
    path.join(contractDirectory, "fixtures/accepted"),
  );

  assert.deepEqual(files.sort(), Object.keys(index.accepted).sort());
  for (const file of files) {
    const fixture = await readJson(`fixtures/accepted/${file}`);
    assert.ok(validate(fixture), `${file}: ${JSON.stringify(validate.errors)}`);
  }
});

test("rejected fixtures are refused, each by the validator that owns the rule", async () => {
  const validate = await changeSetValidator();
  const index = await readJson("fixtures/index.json");
  const files = await readdir(
    path.join(contractDirectory, "fixtures/rejected"),
  );

  assert.deepEqual(files.sort(), Object.keys(index.rejected).sort());
  for (const file of files) {
    const fixture = await readJson(`fixtures/rejected/${file}`);
    const expected = index.rejected[file].by;
    if (expected === "envelope") {
      assert.equal(validate(fixture), false, `${file} should not validate`);
      continue;
    }
    // The envelope deliberately does not police block payloads; the canonical
    // block schema does. A fixture that survives the first and dies on the
    // second is what proves both are actually running.
    assert.ok(validate(fixture), `${file}: ${JSON.stringify(validate.errors)}`);
    assert.equal(await blockDataAccepted(fixture), false, `${file} block data`);
  }
});

test("no command can move a published address", async () => {
  const schema = await readJson("content-change-set.v1.schema.json");
  // The URL workflow refuses automation outright, so the contract must not
  // offer a field an optimiser could reach for.
  const serialised = JSON.stringify(schema.$defs);
  assert.ok(!serialised.includes('"slug"') || !serialised.includes("url"));
  assert.deepEqual(
    Object.keys(
      schema.$defs.commandTranslationUpdate.properties.fields.properties,
    ),
    ["title", "description", "social_title", "social_description"],
  );
});
