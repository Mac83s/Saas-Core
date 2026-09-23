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

// What the import binds in place of a materialized tenant asset.
const PLACEHOLDER_ASSET_ID = "00000000-0000-4000-8000-000000000000";

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

/** The PL blocks and, when present, the EN seed, each as [locale, blocks]. */
function variants(recipe) {
  return [
    ["pl", recipe.blocks],
    ...(recipe.localizedBlocks ? [["en", recipe.localizedBlocks.en]] : []),
  ];
}

/** Same rule as `setAtPath` in @saas-core/site-blocks and the backend import:
 *  the parent must exist, and the last segment is a key of an object or an
 *  index into an array no greater than its length (equal appends). */
function setAtPath(target, segments, value) {
  let parent = target;
  for (const segment of segments.slice(0, -1)) {
    const keyed = Array.isArray(parent)
      ? Number.isInteger(segment)
      : typeof segment === "string";
    parent = keyed ? parent[segment] : undefined;
    if (parent === null || typeof parent !== "object")
      throw new TypeError(`${segments.join(".")} has no parent`);
  }
  const last = segments.at(-1);
  if (Array.isArray(parent)) {
    if (!Number.isInteger(last) || last < 0 || last > parent.length)
      throw new TypeError(`${segments.join(".")} is outside the array`);
  } else if (typeof last !== "string") {
    throw new TypeError(`${segments.join(".")} does not name a key`);
  }
  parent[last] = value;
}

/** The blocks an import would produce, with every photo bound in order. */
function boundBlocks(recipe, blocks, locale) {
  const bound = structuredClone(blocks);
  for (const binding of recipe.mediaBindings ?? []) {
    const block = bound[binding.blockPosition];
    assert.ok(block, `${recipe.id}: binding past the last block`);
    setAtPath(block.data, binding.path ?? ["image"], {
      asset_id: PLACEHOLDER_ASSET_ID,
      alt: binding.alt[locale],
    });
  }
  return bound;
}

/** Calls `visit(key, value)` for every property anywhere inside `value`. */
function walk(value, visit) {
  if (Array.isArray(value)) {
    for (const child of value) walk(child, visit);
  } else if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      visit(key, child);
      walk(child, visit);
    }
  }
}

function headingAnchors(blocks) {
  const anchors = [];
  for (const block of blocks) {
    if (block.block_type !== "core.rich_text") continue;
    walk(block.data, (key, value) => {
      if (key === "anchor") anchors.push(value);
    });
  }
  return anchors;
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
      "core.medicine_clinic",
      "core.agriculture_services",
      "core.electronics_service",
      "core.business_studio",
      "core.product_first_impression",
      "core.service_guide",
      "core.expert_knowledge",
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

test("template blocks validate against the canonical block contracts once their photos are bound", async () => {
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
    for (const [locale, blocks] of variants(recipe)) {
      // A binding may target any slot the block contract accepts: a hero
      // photo, a product gallery entry, a figure inside rich text. The block
      // is judged after binding, exactly as the import will save it.
      for (const [index, block] of boundBlocks(
        recipe,
        blocks,
        locale,
      ).entries()) {
        const where = `${recipe.id} v${recipe.version} ${locale} block ${index}`;
        const known = validators.get(block.block_type);
        // A recipe naming a block the deployment does not have would produce a
        // draft the renderer cannot show and the backend refuses to save.
        assert.ok(known, `${where}: unknown type ${block.block_type}`);
        // Immutable historical recipes remain valid; editing migrates their blocks.
        assert.ok(
          block.schema_version <= known.latest,
          `${where}: ${block.block_type} must use a supported version`,
        );
        const validate = known.byVersion.get(block.schema_version);
        assert.ok(validate, `${where}: unknown version`);
        assert.equal(
          validate(block.data),
          true,
          `${where}: ${JSON.stringify(validate.errors)}`,
        );
      }
    }
  }
});

test("media bindings address one existing slot each", async () => {
  const { templates } = await loadTemplates();

  for (const { recipe } of templates) {
    const slots = new Set();
    for (const binding of recipe.mediaBindings ?? []) {
      const slot = JSON.stringify([
        binding.blockPosition,
        binding.path ?? ["image"],
      ]);
      // Two photos for one slot would silently keep only the last.
      assert.ok(!slots.has(slot), `${recipe.id}: duplicate binding ${slot}`);
      slots.add(slot);
    }
    // A path whose parent is missing, or an index past the end of its array,
    // is a recipe error rather than something the import may patch up.
    for (const [locale, blocks] of variants(recipe))
      assert.doesNotThrow(
        () => boundBlocks(recipe, blocks, locale),
        `${recipe.id} ${locale}`,
      );
  }

  const block = { data: { images: [], content: [{ type: "figure" }] } };
  assert.doesNotThrow(() => setAtPath(block.data, ["images", 0], {}));
  assert.doesNotThrow(() => setAtPath(block.data, ["content", 0, "image"], {}));
  assert.throws(() => setAtPath(block.data, ["images", 2], {}));
  assert.throws(() => setAtPath(block.data, ["gallery", 0], {}));
  assert.throws(() => setAtPath(block.data, ["content", 1, "image"], {}));
});

test("recipe data never carries a media asset id", async () => {
  const { templates } = await loadTemplates();

  for (const { recipe } of templates) {
    // No demo UUID may leak into a recipe: media is assigned during import.
    for (const [locale, blocks] of variants(recipe))
      walk(blocks, (key) =>
        assert.notEqual(
          key,
          "asset_id",
          `${recipe.id} v${recipe.version} ${locale}`,
        ),
      );
  }
});

test("template link targets stay inside the allowed href forms", async () => {
  const { templates } = await loadTemplates();
  const allowed =
    /^(?:\/(?!\/)|https:\/\/|mailto:|tel:|#[a-z][a-z0-9-]{0,63}$)/;

  for (const { recipe } of templates) {
    for (const [locale, blocks] of variants(recipe)) {
      const anchors = new Set(headingAnchors(blocks));
      walk(blocks, (key, href) => {
        if (key !== "href") return;
        assert.match(
          href,
          allowed,
          `${recipe.id} ${locale}: seeded href ${href} is not an allowed form`,
        );
        // An in-page link must land on a heading of the same page variant.
        if (href.startsWith("#"))
          assert.ok(
            anchors.has(href.slice(1)),
            `${recipe.id} ${locale}: ${href} has no heading`,
          );
      });
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

test("recipe presentation envelopes validate against their own contracts", async () => {
  const { templates } = await loadTemplates();
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  // The recipe schema only says "object" here on purpose: each envelope has
  // one owner, and a second copy of its enums would drift.
  const validatePage = ajv.compile(
    await readJson("site-blocks", "page-presentation.v1.schema.json"),
  );
  const envelopes = {
    decoration: ajv.compile(
      await readJson("site-blocks", "section-decoration.v1.schema.json"),
    ),
    presentation: ajv.compile(
      await readJson("site-blocks", "section-presentation.v1.schema.json"),
    ),
  };

  for (const { recipe } of templates) {
    if (recipe.pagePresentation !== undefined)
      assert.equal(
        validatePage(recipe.pagePresentation),
        true,
        `${recipe.id}: ${JSON.stringify(validatePage.errors)}`,
      );
    for (const [locale, blocks] of variants(recipe)) {
      for (const [index, block] of blocks.entries()) {
        for (const [key, validate] of Object.entries(envelopes)) {
          if (block[key] === undefined) continue;
          assert.equal(
            validate(block[key]),
            true,
            `${recipe.id} ${locale} block ${index} ${key}: ${JSON.stringify(validate.errors)}`,
          );
        }
      }
    }
  }
});

test("rich text heading anchors are unique within each recipe variant", async () => {
  const { templates } = await loadTemplates();

  for (const { recipe } of templates) {
    for (const [locale, blocks] of variants(recipe)) {
      const anchors = headingAnchors(blocks);
      // The backend refuses a draft with a repeated anchor, so an import of
      // such a recipe would fail on its first save.
      assert.equal(
        new Set(anchors).size,
        anchors.length,
        `${recipe.id} ${locale}: ${anchors.join(", ")}`,
      );
    }
  }
});

test("composed page recipes pin section versions and materialize their exact seed data", async () => {
  const { templates } = await loadTemplates();
  const catalogs = await Promise.all(
    [1, 2, 3, 4, 5].map((version) =>
      readJson("site-blocks", `section-templates.v${version}.json`),
    ),
  );
  const sections = catalogs.flatMap((catalog) => catalog.templates);
  const industries = new Set(catalogs.at(-1).industries.map((item) => item.id));
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
      const section = sections.find(
        (item) => item.id === ref.id && item.version === ref.version,
      );
      assert.ok(section, `Missing pinned section ${ref.id}@${ref.version}`);
      // Envelopes are the recipe's own choice; only the content is pinned.
      const { block_type, schema_version, data } = recipe.blocks[ref.position];
      assert.deepEqual(
        { block_type, schema_version, data },
        {
          block_type: section.blockType,
          schema_version: section.schemaVersion,
          data: section.seed.pl,
        },
      );
    }
  }
});

test("latest complete pages contain localized seeds and bound example photographs", async () => {
  const { templates } = await loadTemplates();
  const photos = await readJson("page-templates", "sample-media.v1.json");
  for (const { entry, version, recipe } of templates) {
    if (version !== entry.latestVersion) continue;
    assert.equal(recipe.localizedBlocks.en.length, recipe.blocks.length);
    // The EN seed is the same page in another language, not another page:
    // bindings and section positions address both.
    for (const [index, block] of recipe.blocks.entries()) {
      const localized = recipe.localizedBlocks.en[index];
      assert.equal(localized.block_type, block.block_type, recipe.id);
      assert.equal(localized.schema_version, block.schema_version, recipe.id);
    }
    assert.ok(recipe.mediaBindings.length > 0, recipe.id);
    for (const binding of recipe.mediaBindings) {
      const medium = recipe.media.find((item) => item.id === binding.mediaId);
      assert.ok(medium, recipe.id);
      assert.ok(
        photos.media.some(
          (item) => item.id === medium.id && item.sha256 === medium.sha256,
        ),
      );
      for (const locale of ["pl", "en"])
        assert.ok(binding.alt[locale].length > 0);
    }
  }
});
