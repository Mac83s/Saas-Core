import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
    [
      "core.profile",
      "core.specialist_landing",
      "core.company",
      "core.service_landing",
    ],
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
      // Immutable historical recipes remain valid; editing migrates their blocks.
      assert.ok(
        block.schema_version <= known.latest,
        `${recipe.id} block ${index}: ${block.block_type} must use a supported version`,
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

test("approved template media stays local and content-addressed", async () => {
  const { templates } = await loadTemplates();
  const assetRoot = path.resolve(contractRoot, "page-templates", "assets");

  for (const { recipe } of templates) {
    const ids = new Set();
    for (const media of recipe.media ?? []) {
      assert.equal(
        ids.has(media.id),
        false,
        `${recipe.id}: duplicate media id`,
      );
      ids.add(media.id);
      const source = path.resolve(contractRoot, "page-templates", media.source);
      assert.equal(
        path.relative(assetRoot, source).startsWith(".."),
        false,
        `${recipe.id}: media leaves the approved asset directory`,
      );
      const content = await readFile(source);
      assert.equal(content.length > 0, true, `${recipe.id}: empty media`);
      assert.equal(
        createHash("sha256").update(content).digest("hex"),
        media.sha256,
        `${recipe.id}: media checksum mismatch`,
      );
    }
  }
});

test("recipe schema accepts only explicit approved image metadata", async () => {
  const { validateRecipe, templates } = await loadTemplates();
  const candidate = structuredClone(templates[0].recipe);
  candidate.media = [
    {
      id: "hero",
      source: "assets/profile/hero.webp",
      filename: "hero.webp",
      contentType: "image/webp",
      sha256: "a".repeat(64),
    },
  ];
  assert.equal(
    validateRecipe(candidate),
    true,
    JSON.stringify(validateRecipe.errors),
  );

  candidate.media[0].contentType = "image/svg+xml";
  assert.equal(validateRecipe(candidate), false);
});

test("composed page recipes pin section versions and materialize their exact seed data", async () => {
  const { templates } = await loadTemplates();
  const catalog = await readJson("site-blocks", "section-templates.v1.json");
  const industries = new Set(catalog.industries.map((item) => item.id));
  for (const { recipe } of templates) {
    for (const industry of recipe.industries ?? [])
      assert.ok(industries.has(industry));
    const positions = new Set();
    for (const ref of recipe.sectionRefs ?? []) {
      assert.ok(
        !positions.has(ref.position),
        "section position must be unique",
      );
      positions.add(ref.position);
      const section = catalog.templates.find(
        (item) => item.id === ref.id && item.version === ref.version,
      );
      assert.ok(section, `Missing pinned section ${ref.id}@${ref.version}`);
      assert.deepEqual(recipe.blocks[ref.position], {
        block_type: section.blockType,
        schema_version: section.schemaVersion,
        data: section.seed.pl,
      });
    }
  }
});
