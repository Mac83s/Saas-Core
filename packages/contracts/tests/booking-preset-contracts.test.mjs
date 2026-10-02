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

async function loadPresets() {
  const manifest = await readJson("booking-presets", "manifest.json");
  const schema = await readJson("booking-presets", manifest.schema);
  const validate = new Ajv2020({ allErrors: true, strict: true }).compile(
    schema,
  );
  const presets = [];
  for (const entry of manifest.presets) {
    for (const [version, file] of Object.entries(entry.versions)) {
      presets.push({
        entry,
        version: Number(version),
        file,
        preset: await readJson("booking-presets", file),
      });
    }
  }
  return { manifest, validate, presets };
}

/** The latest version of every preset a company may still be offered. */
function offered(presets) {
  return presets.filter(
    ({ entry, version }) =>
      entry.retired !== true && version === entry.latestVersion,
  );
}

const where = ({ preset }) => `${preset.id} v${preset.version}`;

// The owner's catalogue (plan `saas-core-rezerwacje-uniwersalne-i-sprzedaz`,
// "Katalog presetów"), in the order a company sees it at setup: all thirteen
// are visible, ready or "soon" (answer 14 a+b of 01.10.2026).
const CATALOGUE = [
  "core.specialist_visit",
  "core.online_visit",
  "core.service_at_customer",
  "core.hourly_space",
  "core.table_or_group",
  "core.lodging",
  "core.rental",
  "core.care_stay",
  "core.exclusive_date",
  "core.group_class",
  "core.ticketed_event",
  "core.course",
  "core.pickup_window",
];

// What the booking engine of this core version runs (ADR-072 §10). A preset
// marked "ready" may use nothing else. The phase that teaches the engine more
// widens this list in the same change as the preset versions it makes ready.
const ENGINE = {
  timeModel: ["slot"],
  subject: ["staff"],
  quantity: ["one"],
  participants: ["none"],
  confirmation: ["instant"],
  place: ["business"],
};

const PREPAID = ["transfer", "deposit", "full"];

// The only catalogue category the plan's preset table and the assistant plan
// name (Nocleg → turystyka-i-noclegi). A "soon" preset carries no other: the
// phase that makes a preset ready may propose one with the ready version.
const PLAN_CATEGORIES = { "core.lodging": "turystyka-i-noclegi" };

test("every preset matches the schema and its manifest entry", async () => {
  const { manifest, validate, presets } = await loadPresets();

  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.schema, "booking-preset.v1.schema.json");
  const ids = manifest.presets.map((entry) => entry.id);
  assert.equal(new Set(ids).size, ids.length, "preset ids must be unique");

  for (const entry of manifest.presets) {
    assert.ok(
      entry.retired === undefined || entry.retired === true,
      `${entry.id}: retired is either true or absent`,
    );
    assert.deepEqual(
      Object.keys(entry.versions)
        .map(Number)
        .sort((a, b) => a - b),
      Array.from({ length: entry.latestVersion }, (_, index) => index + 1),
      `${entry.id} versions must run from 1 to latestVersion`,
    );
  }

  for (const item of presets) {
    const { entry, version, file, preset } = item;
    assert.equal(
      validate(preset),
      true,
      `${entry.id} v${version}: ${JSON.stringify(validate.errors)}`,
    );
    assert.equal(preset.id, entry.id);
    assert.equal(preset.version, version);
    // The file name is the address a version keeps for good.
    assert.equal(file, `${entry.id}.v${version}.json`, where(item));
  }
});

test("the manifest offers the whole catalogue in the owner's order", async () => {
  const { manifest, presets } = await loadPresets();

  assert.deepEqual(
    manifest.presets.map((entry) => entry.id),
    CATALOGUE,
  );
  assert.equal(offered(presets).length, CATALOGUE.length);
  // Answer 14 a+b: what is not ready yet is still shown, labelled "soon".
  assert.ok(
    offered(presets).some(({ preset }) => preset.readiness === "ready"),
    "at least one preset runs today",
  );
});

test("each time model carries its own settings and only them", async () => {
  const { presets } = await loadPresets();

  for (const item of presets) {
    const { preset } = item;
    const { timeModel, booked, quantity } = preset;
    // A period names its unit of time; a slot and a session never do.
    assert.equal(
      preset.range !== undefined,
      timeModel === "range",
      `${where(item)}: range settings belong to range presets only`,
    );
    assert.equal(
      preset.session !== undefined,
      timeModel === "session",
      `${where(item)}: session settings belong to session presets only`,
    );
    // Counted seats exist only in a session (ADR-072 §3); everything else
    // books single, exclusive people or units the exclusion constraint guards.
    assert.equal(
      booked.subject === "seat",
      timeModel === "session",
      where(item),
    );
    assert.equal(quantity === "seats", timeModel === "session", where(item));
    if (quantity === "units")
      assert.equal(
        booked.subject,
        "unit_group",
        `${where(item)}: N units come from a group`,
      );
    if (booked.subject === "staff")
      assert.equal(booked.staff, "required", where(item));
    if (timeModel === "range" && preset.range.unit === "hour")
      assert.equal(preset.range.startTime, undefined, where(item));
    if (preset.price?.basis === "per_time_unit")
      assert.equal(
        timeModel,
        "range",
        `${where(item)}: only a period is priced per unit of time`,
      );
  }
});

test("vocabulary speaks pl and en and names what the preset books", async () => {
  const { presets } = await loadPresets();

  for (const item of presets) {
    const { preset } = item;
    const books = ["unit", "unit_group"].includes(preset.booked.subject);
    for (const locale of ["pl", "en"])
      assert.ok(
        preset.labels[locale]?.name,
        `${where(item)}: labels.${locale}`,
      );
    // A "soon" preset may leave its words to the ready version (ADR-072 §10);
    // a ready one is applied to an offer, so it must carry them.
    if (preset.vocabulary === undefined) {
      assert.equal(preset.readiness, "soon", `${where(item)}: vocabulary`);
      continue;
    }
    for (const locale of ["pl", "en"])
      assert.ok(
        preset.vocabulary[locale],
        `${where(item)}: vocabulary.${locale}`,
      );
    // The panel and the site take these words from the offer, in every
    // language the preset speaks: a unit preset without a word for its unit
    // would fall back to "Zasoby".
    for (const [locale, terms] of Object.entries(preset.vocabulary)) {
      assert.equal(
        terms.unit !== undefined,
        books,
        `${where(item)} ${locale}: unit words exactly when a unit is booked`,
      );
      assert.equal(
        terms.timeUnit !== undefined,
        preset.timeModel === "range",
        `${where(item)} ${locale}: time unit words exactly for a period`,
      );
    }
  }
});

test("keys are unique where the offer will address them", async () => {
  const { presets } = await loadPresets();

  const unique = (list, label) => {
    const keys = list.map((item) => item.key);
    assert.equal(new Set(keys).size, keys.length, label);
  };
  for (const item of presets) {
    const { preset } = item;
    const fields = preset.fields ?? [];
    unique(fields, `${where(item)}: field keys`);
    unique(preset.extras ?? [], `${where(item)}: extra keys`);
    unique(preset.participants?.categories ?? [], `${where(item)}: categories`);
    for (const field of fields)
      unique(field.options ?? [], `${where(item)}: options of ${field.key}`);
  }
});

test("payment and cancellation defaults are consistent", async () => {
  const { presets } = await loadPresets();

  for (const item of presets) {
    const { payment, cancellation } = item.preset;
    if (cancellation === undefined) continue;
    // A refund needs something paid before the stay or the visit.
    assert.ok(
      PREPAID.includes(payment?.policy),
      `${where(item)}: refund thresholds without a prepaid policy`,
    );
    // Thresholds on the deposit need a deposit (answer 13a: "zwrot zadatku").
    if (cancellation.appliesTo === "deposit")
      assert.equal(payment.policy, "deposit", where(item));
    const { refunds } = cancellation;
    for (const [index, threshold] of refunds.entries()) {
      if (index === 0) continue;
      const previous = refunds[index - 1];
      // From the longest notice down: less notice never refunds more.
      assert.ok(threshold.minDaysBefore < previous.minDaysBefore, where(item));
      assert.ok(threshold.refundPercent <= previous.refundPercent, where(item));
    }
    // Every notice falls under some threshold, the last one at day zero.
    assert.equal(refunds.at(-1).minDaysBefore, 0, where(item));
  }
});

test("a ready preset uses only what this core's booking engine runs", async () => {
  const { presets } = await loadPresets();

  for (const item of offered(presets)) {
    const { preset } = item;
    if (preset.readiness !== "ready") continue;
    assert.ok(ENGINE.timeModel.includes(preset.timeModel), where(item));
    assert.ok(ENGINE.subject.includes(preset.booked.subject), where(item));
    assert.ok(ENGINE.quantity.includes(preset.quantity), where(item));
    assert.ok(
      ENGINE.participants.includes(preset.participants.mode),
      where(item),
    );
    assert.ok(ENGINE.confirmation.includes(preset.confirmation), where(item));
    assert.ok(ENGINE.place.includes(preset.place), where(item));
    // Prices, payments, custom fields and extras arrive with phases 3-5.
    for (const key of ["price", "payment", "cancellation"])
      assert.equal(preset[key], undefined, `${where(item)}: ${key}`);
    assert.deepEqual(preset.fields, [], where(item));
    assert.deepEqual(preset.extras, [], where(item));
  }
});

test("suggested page templates and catalogue categories exist", async () => {
  const { presets } = await loadPresets();
  const templates = await readJson("page-templates", "manifest.json");
  const catalog = await readJson("catalog", "manifest.json");
  const offeredTemplates = new Set(
    templates.templates
      .filter((entry) => entry.retired !== true)
      .map((entry) => entry.id),
  );
  // Categories are keyed by organization type; a core preset may suggest any
  // category the core dictionary has (a product's own types bring their own).
  const categories = new Set(
    Object.values(catalog.categories).flatMap((list) =>
      list.map((category) => category.key),
    ),
  );

  for (const item of offered(presets)) {
    const { pageTemplate, catalogCategory } = item.preset;
    if (pageTemplate !== undefined)
      assert.ok(
        offeredTemplates.has(pageTemplate),
        `${where(item)}: page template ${pageTemplate}`,
      );
    if (catalogCategory !== undefined)
      assert.ok(
        categories.has(catalogCategory),
        `${where(item)}: catalogue category ${catalogCategory}`,
      );
    // A "soon" preset carries only what the plan says (ADR-072 §10).
    if (item.preset.readiness === "soon" && catalogCategory !== undefined)
      assert.equal(
        catalogCategory,
        PLAN_CATEGORIES[item.preset.id],
        `${where(item)}: catalogue category outside the plan`,
      );
  }
});

test("the schema refuses what a preset may not say", async () => {
  const { validate, presets } = await loadPresets();
  const lodging = presets.find(({ preset }) => preset.id === "core.lodging");
  const visit = presets.find(
    ({ preset }) => preset.id === "core.specialist_visit",
  );
  const refused = (base, change) => {
    const candidate = structuredClone(base.preset);
    change(candidate);
    return validate(candidate) === false;
  };

  // Further content languages are optional, as long as pl and en are there.
  assert.ok(
    !refused(lodging, (preset) => {
      preset.labels.de = { name: "Unterkunft", description: "Ferienhaus." };
    }),
    JSON.stringify(validate.errors),
  );
  assert.ok(refused(lodging, (preset) => delete preset.vocabulary.en));
  assert.ok(
    refused(lodging, (preset) => {
      preset.labels["pl-PL"] = preset.labels.pl;
    }),
  );
  // No money and no tax rate: both depend on the company's currency and
  // country (ADR-072 §10).
  assert.ok(
    refused(lodging, (preset) => {
      preset.extras[0].amountMinor = 20000;
    }),
  );
  assert.ok(
    refused(lodging, (preset) => {
      preset.price.currency = "PLN";
    }),
  );
  // A period without its unit, a slot with one, an hour with check-in times.
  assert.ok(refused(lodging, (preset) => delete preset.range));
  assert.ok(
    refused(visit, (preset) => {
      preset.range = { unit: "night" };
    }),
  );
  assert.ok(
    refused(lodging, (preset) => {
      preset.range.unit = "hour";
    }),
  );
  // A deposit percentage means a deposit; a seat means a session.
  assert.ok(
    refused(lodging, (preset) => {
      preset.payment.policy = "on_site";
    }),
  );
  assert.ok(
    refused(visit, (preset) => {
      preset.booked = { subject: "seat", staff: "none" };
    }),
  );
  // Refund thresholds say what they apply to: the deposit or all payments
  // (ADR-072 §8; answer 13a speaks of the deposit).
  assert.ok(refused(lodging, (preset) => delete preset.cancellation.appliesTo));
  assert.ok(
    refused(lodging, (preset) => {
      preset.cancellation.appliesTo = "balance";
    }),
  );
  // A ready preset is applied to an offer, so it carries its words, fields,
  // extras and participants; a "soon" one may leave them to its ready version.
  for (const key of ["vocabulary", "fields", "extras", "participants"])
    assert.ok(
      refused(visit, (preset) => delete preset[key]),
      `ready without ${key}`,
    );
  assert.ok(
    !refused(lodging, (preset) => {
      for (const key of ["vocabulary", "fields", "extras", "participants"])
        delete preset[key];
    }),
    JSON.stringify(validate.errors),
  );
  // The field is readiness, not availability: in booking that word means
  // free time (AvailabilityRule, available_slots).
  assert.ok(
    refused(visit, (preset) => {
      preset.availability = preset.readiness;
      delete preset.readiness;
    }),
  );
  // Required inputs are keys the assistant's configurator reads, not prose.
  assert.ok(
    refused(lodging, (preset) => {
      preset.requiredInputs = ["Daty sezonów"];
    }),
  );
  assert.ok(
    refused(lodging, (preset) => {
      preset.requiredInputs = ["photos", "photos"];
    }),
  );
});
