import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";

const contractRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

async function readJson(...segments) {
  return JSON.parse(
    await readFile(path.join(contractRoot, ...segments), "utf8"),
  );
}

async function loadTemplates() {
  const manifest = await readJson("page-templates", "manifest.json");
  const recipeSchema = await readJson("page-templates", manifest.recipe);
  const validateRecipe = new Ajv2020({ allErrors: true, strict: true }).compile(
    recipeSchema,
  );
  const templates = [];
  for (const entry of manifest.templates) {
    for (const [version, file] of Object.entries(entry.versions)) {
      templates.push({
        entry,
        version: Number(version),
        recipe: await readJson("page-templates", file),
      });
    }
  }
  return { manifest, validateRecipe, templates };
}

test("every template recipe matches the recipe schema and its manifest entry", async () => {
  const { manifest, validateRecipe, templates } = await loadTemplates();

  assert.equal(manifest.schemaVersion, 1);
  assert.deepEqual(
    manifest.templates.map((entry) => entry.id),
    ["core.profile", "core.specialist_landing", "core.company"],
  );

  for (const { entry, version, recipe } of templates) {
    assert.equal(
      validateRecipe(recipe),
      true,
      `${entry.id} v${version}: ${JSON.stringify(validateRecipe.errors)}`,
    );
    assert.equal(recipe.id, entry.id);
    assert.equal(recipe.version, version);
  }

  for (const entry of manifest.templates) {
    assert.deepEqual(
      Object.keys(entry.versions).map(Number).sort(),
      Array.from({ length: entry.latestVersion }, (_, index) => index + 1),
      `${entry.id} versions must run from 1 to latestVersion`,
    );
  }
});

test("template blocks validate against the canonical block contracts", async () => {
  const { templates } = await loadTemplates();
  const blockManifest = await readJson("site-blocks", "manifest.json");
  const ajv = new Ajv2020({ allErrors: true, strict: true });

  const validators = new Map();
  for (const block of blockManifest.blocks) {
    const byVersion = new Map();
    for (const [version, file] of Object.entries(block.schemas)) {
      byVersion.set(
        Number(version),
        ajv.compile(await readJson("site-blocks", file)),
      );
    }
    validators.set(block.type, { byVersion, latest: block.latestVersion });
  }

  for (const { recipe } of templates) {
    for (const [index, block] of recipe.blocks.entries()) {
      const known = validators.get(block.block_type);
      // A recipe naming a block the deployment does not have would produce a
      // draft the renderer cannot show and the backend refuses to save.
      assert.ok(
        known,
        `${recipe.id} block ${index}: unknown type ${block.block_type}`,
      );
      // Seeding an outdated version would hand every new page a draft that is
      // already pending migration.
      assert.equal(
        block.schema_version,
        known.latest,
        `${recipe.id} block ${index}: ${block.block_type} should seed v${known.latest}`,
      );
      const validate = known.byVersion.get(block.schema_version);
      assert.ok(validate, `${recipe.id} block ${index}: unknown version`);
      assert.equal(
        validate(block.data),
        true,
        `${recipe.id} block ${index}: ${JSON.stringify(validate.errors)}`,
      );
    }
  }
});

test("template link targets stay inside the allowed href forms", async () => {
  const { templates } = await loadTemplates();
  const allowed = /^(?:\/|https:\/\/|mailto:|tel:)/;

  for (const { recipe } of templates) {
    for (const block of recipe.blocks) {
      const href = block.data?.action?.href;
      if (href === undefined) continue;
      assert.match(
        href,
        allowed,
        `${recipe.id}: seeded href ${href} is not an allowed form`,
      );
    }
  }
});
