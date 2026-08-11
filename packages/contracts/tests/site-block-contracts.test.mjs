import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";

const contractDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../site-blocks",
);

async function readJson(relativePath) {
  return JSON.parse(
    await readFile(path.join(contractDirectory, relativePath), "utf8"),
  );
}

test("site block manifest references valid canonical schemas", async () => {
  const manifest = await readJson("manifest.json");
  const ajv = new Ajv2020({ allErrors: true, strict: true });

  assert.equal(manifest.schemaVersion, 1);
  assert.deepEqual(
    manifest.blocks.map((block) => block.type),
    ["core.hero", "core.rich_text"],
  );

  for (const block of manifest.blocks) {
    const versions = Object.keys(block.schemas).map(Number);
    assert.deepEqual(
      versions,
      Array.from({ length: block.latestVersion }, (_, index) => index + 1),
    );
    for (const schemaPath of Object.values(block.schemas)) {
      const schema = await readJson(schemaPath);
      ajv.compile(schema);
    }
  }

  ajv.compile(await readJson(manifest.designTokens));
});

test("backward compatibility fixture matches hero v1", async () => {
  const fixture = await readJson("fixtures/core.hero.v1.json");
  const schema = await readJson("core.hero.v1.schema.json");
  const validate = new Ajv2020({ strict: true }).compile(schema);

  assert.equal(validate(fixture.data), true, JSON.stringify(validate.errors));
});
