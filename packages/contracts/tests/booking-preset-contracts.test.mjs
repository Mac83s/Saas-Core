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
  timeModel: ["slot", "range"],
  // A period by the night or by the day; hours come later
  // (`range_unit_not_ready`), so „Wynajem przestrzeni na godziny” stays "soon".
  rangeUnit: ["night", "day"],
  subject: ["staff", "unit", "unit_group"],
  // One person's visit or one unit's stay per booking; N units at once and
  // counted seats are not booked yet.
  quantity: ["one"],
  participants: ["none", "count", "categories"],
  confirmation: ["instant"],
  place: ["business", "customer", "pickup_return"],
  // Paying before the stay came with orders (ADR-073, phase 4): a transfer
  // with a date, a prepayment and its balance, refund thresholds.
  paymentPolicy: ["none", "on_site", "transfer", "deposit", "full"],
};
// What the public booking form takes today, by time model and place: a visit
// by the clock at the company's place, and — since phase 5b — a stay or a
// rental booked from–to. Every other ready preset says "soon" for booking
// through the site (owner decision 67a): the team books it in the panel.
const ONLINE = {
  slot: ["business"],
  range: ["business", "pickup_return"],
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

test("presets speak only languages of the content-language registry", async () => {
  const { presets } = await loadPresets();
  const registry = await readJson("locales", "registry.json");
  const known = new Set(registry.locales.map((locale) => locale.code));

  // The schema checks only the shape ^[a-z]{2}$, which would let "cz" through;
  // a content language is a registry entry (ADR-071 pkt 2, ADR-072 §10).
  for (const item of presets) {
    const { preset } = item;
    const texts = [
      preset.labels,
      preset.vocabulary ?? {},
      ...(preset.participants?.categories ?? []).map((entry) => entry.labels),
      ...(preset.extras ?? []).map((extra) => extra.labels),
      ...(preset.fields ?? []).flatMap((field) => [
        field.labels,
        ...(field.options ?? []).map((option) => option.labels),
      ]),
    ];
    for (const text of texts)
      for (const locale of Object.keys(text))
        assert.ok(known.has(locale), `${where(item)}: language ${locale}`);
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
  // Owner decision 28a: in Nocleg the switch "Progi zwrotu obejmują też
  // dopłatę" is off, so the thresholds cover the deposit and the balance
  // comes back in full. The version that runs before orders exist carries no
  // thresholds at all; whichever version does, keeps the switch off.
  const lodging = presets.filter(
    ({ preset }) =>
      preset.id === "core.lodging" && preset.cancellation !== undefined,
  );
  assert.ok(lodging.length > 0);
  for (const item of lodging)
    assert.equal(item.preset.cancellation.appliesTo, "deposit", where(item));
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
    if (preset.timeModel === "range") {
      assert.ok(ENGINE.rangeUnit.includes(preset.range.unit), where(item));
      // A stay takes a unit and nobody's time (ADR-072 §2).
      assert.equal(preset.booked.staff, "none", where(item));
      assert.notEqual(preset.booked.subject, "staff", where(item));
      // Season rules are the company's own dated rows, never a preset's.
      assert.equal(preset.range.rules, undefined, where(item));
    } else {
      assert.equal(preset.booked.subject, "staff", where(item));
    }
    // The price list, extras and the security deposit are here (phase 3),
    // prepayments and refund thresholds since orders (phase 4); custom
    // fields come with the public form (phase 5), portal calendars with
    // phase 6.
    assert.ok(
      ENGINE.paymentPolicy.includes(preset.payment?.policy ?? "none"),
      `${where(item)}: payment policy`,
    );
    assert.deepEqual(preset.fields, [], where(item));
    assert.equal(preset.calendarSync, false, where(item));
    // Nothing asks the company for inputs no command can save yet.
    assert.equal(preset.requiredInputs, undefined, where(item));
    if ((preset.onlineBooking ?? "ready") === "ready") {
      assert.ok(
        ONLINE[preset.timeModel]?.includes(preset.place),
        `${where(item)}: not booked through the site yet`,
      );
      // What is booked through the site does not say it is coming.
      assert.doesNotMatch(preset.labels.pl.description, /wkrótce/, where(item));
      assert.doesNotMatch(
        preset.labels.en.description,
        /coming soon/,
        where(item),
      );
    } else {
      // Said plainly where the company reads it, in both languages.
      assert.match(
        preset.labels.pl.description,
        /rezerwacja przez stronę.* — wkrótce/,
        where(item),
      );
      assert.match(
        preset.labels.en.description,
        /booking through the site/,
        where(item),
      );
    }
  }
});

test("what the engine runs today is ready, the rest is announced", async () => {
  const { presets } = await loadPresets();
  const readiness = Object.fromEntries(
    offered(presets).map(({ preset }) => [
      preset.id,
      `${preset.readiness} v${preset.version}`,
    ]),
  );

  // Owner decisions 67a and 68a (03.10.2026): stays, rentals and care stays
  // are ready once the price list is there, and the service at the
  // customer's in a reduced version — without waiting for the public form.
  // Version 4 of the stay adds terms of paying ahead and of giving a stay up,
  // as a start the company changes (ADR-073, „Uzupełnienie po 4h”).
  // Version 3 of the three kinds booked from–to came with that form (phase
  // 5b): customers book them through the site. Version 5 of the stay
  // suggests the page template „Noclegi” (slice 5g).
  assert.deepEqual(readiness, {
    "core.specialist_visit": "ready v1",
    "core.online_visit": "soon v1",
    "core.service_at_customer": "ready v2",
    "core.hourly_space": "soon v1",
    "core.table_or_group": "soon v1",
    "core.lodging": "ready v5",
    "core.rental": "ready v3",
    "core.care_stay": "ready v3",
    "core.exclusive_date": "soon v1",
    "core.group_class": "soon v1",
    "core.ticketed_event": "soon v1",
    "core.course": "soon v1",
    "core.pickup_window": "soon v1",
  });
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
    // A "soon" preset suggests a catalogue category only where the plan names
    // one (ADR-072 §10); its other values beyond the plan's table are agent
    // proposals its ready version replaces.
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
  // Refund thresholds say what they apply to: the deposit or all payments —
  // the offer's switch (ADR-072 §8, owner decision 28a: the deposit by default).
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
  // Travel time is kept before a visit by the clock; a period has none.
  assert.ok(
    !refused(visit, (preset) => {
      preset.buffers = { beforeMinutes: 30 };
    }),
    JSON.stringify(validate.errors),
  );
  assert.ok(
    refused(lodging, (preset) => {
      preset.buffers = { beforeMinutes: 30 };
    }),
  );
  assert.ok(
    refused(visit, (preset) => {
      preset.buffers = {};
    }),
  );
  // Booking through the site is said of a preset that runs, in two words.
  assert.ok(
    !refused(visit, (preset) => {
      preset.onlineBooking = "soon";
    }),
    JSON.stringify(validate.errors),
  );
  assert.ok(
    refused(lodging, (preset) => {
      preset.onlineBooking = "soon";
    }),
  );
  assert.ok(
    refused(visit, (preset) => {
      preset.onlineBooking = "panel";
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
