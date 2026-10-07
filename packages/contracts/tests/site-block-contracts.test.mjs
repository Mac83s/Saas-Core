import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
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
    [
      "core.hero",
      "core.rich_text",
      "core.feature_list",
      "core.faq",
      "core.contact",
      "core.link_list",
      "core.testimonials",
      "core.pricing",
      "core.booking",
      "core.footer",
      // Not one of the nine ADR-031 sections an operator picks from: the blog
      // index is built from it, and the server fills it in.
      "core.entry_list",
      "core.contact_form",
      "core.separator",
      "core.quote",
      "core.product",
      "core.gallery",
      // A data table in the content of a page or an entry: rows of cells with
      // rich text's inline marks, never HTML.
      "core.table",
      // Offers booked from–to (ADR-072, slice 5d): each carries a choice,
      // the units, prices and free days are read live.
      "core.stay_units",
      "core.stay_search",
      "core.stay_calendar",
      // One unit's card, and the block of the unit's own page (slice 5e).
      "core.stay_unit",
      // Where a unit is: its town, or its own point once the company shows
      // it; the map loads only when the visitor asks (the map block of 5e).
      "core.stay_map",
      // A company's document on its own site (slice 5f part 2): the server
      // builds it for the document's page; nothing anybody writes carries it.
      "core.document",
    ],
  );
  assert.deepEqual(
    manifest.blocks
      .filter((block) => block.serverBuilt)
      .map((block) => block.type),
    ["core.document"],
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

test("backward compatibility fixture matches rich text v1", async () => {
  const fixture = await readJson("fixtures/core.rich_text.v1.json");
  const schema = await readJson("core.rich_text.v1.schema.json");
  const validate = new Ajv2020({ strict: true }).compile(schema);

  assert.equal(validate(fixture.data), true, JSON.stringify(validate.errors));
});

test("section conversions follow their schema and name registered types", async () => {
  const schema = await readJson("section-conversions.v1.schema.json");
  const contract = await readJson("section-conversions.v1.json");
  const manifest = await readJson("manifest.json");
  const validate = new Ajv2020({ allErrors: true, strict: true }).compile(
    schema,
  );

  assert.equal(validate(contract), true, JSON.stringify(validate.errors));
  const types = new Set(manifest.blocks.map((block) => block.type));
  const ids = new Set();
  for (const conversion of contract.conversions) {
    assert.ok(types.has(conversion.from), conversion.id);
    assert.ok(types.has(conversion.to), conversion.id);
    assert.notEqual(conversion.from, conversion.to, conversion.id);
    assert.ok(!ids.has(conversion.id), `duplicate ${conversion.id}`);
    ids.add(conversion.id);
  }
});

/** The block types modules bring (ADR-077): every directory under `modules/`
 *  — a product's own, none in the core — and the test-only vertical. */
async function moduleDirectories() {
  const found = ["fixtures/modules/vertical.sample"];
  const entries = await readdir(path.join(contractDirectory, "modules"), {
    withFileTypes: true,
  }).catch(() => []);
  for (const entry of entries)
    if (entry.isDirectory()) found.push(`modules/${entry.name}`);
  return found;
}

test("a module's block manifest follows its contract", async () => {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  const validate = ajv.compile(
    await readJson("module-manifest.v1.schema.json"),
  );

  for (const directory of await moduleDirectories()) {
    const manifest = await readJson(`${directory}/manifest.json`);
    assert.equal(
      validate(manifest),
      true,
      `${directory}: ${JSON.stringify(validate.errors)}`,
    );
    // The directory names the module, and every type carries the module's id.
    assert.equal(manifest.module, path.basename(directory));
    const prefix = `${manifest.module.replaceAll("-", "_")}.`;
    for (const block of manifest.blocks) {
      assert.ok(block.type.startsWith(prefix), block.type);
      assert.deepEqual(
        Object.keys(block.schemas).map(Number),
        Array.from({ length: block.latestVersion }, (_, index) => index + 1),
        block.type,
      );
      const schemas = {};
      for (const [version, file] of Object.entries(block.schemas)) {
        const schema = await readJson(`${directory}/${file}`);
        // The frontend checks the file it imported by this.
        assert.ok(schema.$id.endsWith(`/${file}`), `${file}: $id`);
        schemas[version] = new Ajv2020({ strict: true }).compile(schema);
      }
      // What only the server builds is in no library.
      assert.ok(!(block.serverBuilt && block.sections), block.type);
      for (const section of block.sections ?? []) {
        assert.ok(section.id.startsWith(`${block.type}_`), section.id);
        const seedValidator = schemas[section.schemaVersion];
        assert.ok(seedValidator, `${section.id}: schemaVersion`);
        for (const locale of ["pl", "en"])
          assert.equal(
            seedValidator(section.seed[locale]),
            true,
            `${section.id} (${locale}): ${JSON.stringify(seedValidator.errors)}`,
          );
      }
    }
  }
});

test("the module manifest contract refuses what is not a module's", async () => {
  const validate = new Ajv2020({ allErrors: true, strict: true }).compile(
    await readJson("module-manifest.v1.schema.json"),
  );
  const sample = await readJson(
    "fixtures/modules/vertical.sample/manifest.json",
  );
  const changed = (change) => {
    const copy = structuredClone(sample);
    change(copy);
    return validate(copy);
  };

  assert.equal(validate(sample), true);
  // A core type, a core module, a two-part type, an unknown key.
  assert.equal(
    changed((manifest) => (manifest.blocks[0].type = "core.hero")),
    false,
  );
  assert.equal(
    changed((manifest) => (manifest.module = "core.organizations")),
    false,
  );
  assert.equal(
    changed((manifest) => (manifest.blocks[0].type = "vertical.sample")),
    false,
  );
  assert.equal(
    changed((manifest) => (manifest.blocks[0].component = "RecordList")),
    false,
  );
  assert.equal(
    changed(
      (manifest) => (manifest.blocks[0].translation.copied.curator = "title"),
    ),
    false,
  );
});
