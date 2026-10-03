import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";

const contractRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "assistant",
);

async function readJson(...segments) {
  return JSON.parse(
    await readFile(path.join(contractRoot, ...segments), "utf8"),
  );
}

// The four businesses the assistant plan names as its golden profiles (A2).
const EXAMPLES = ["hairdresser", "plumber", "cottages", "kayak-rental"];

async function validator() {
  const schema = await readJson("company-profile.v1.schema.json");
  return new Ajv2020({ allErrors: true, strict: true }).compile(schema);
}

test("the company profile schema accepts its examples", async () => {
  const validate = await validator();
  for (const name of EXAMPLES) {
    const example = await readJson("examples", `${name}.json`);
    assert.equal(
      validate(example),
      true,
      `${name}: ${JSON.stringify(validate.errors)}`,
    );
  }
});

test("a value without its origin and confirmation is not a profile's", async () => {
  const validate = await validator();
  const said = { value: "Olsztyn", origin: "owner", confirmed: true };
  const profile = (city) => ({
    schema: "company-profile.v1",
    company: { city },
  });

  assert.equal(validate(profile(said)), true);
  assert.equal(validate(profile("Olsztyn")), false);
  assert.equal(validate(profile({ value: "Olsztyn", origin: "owner" })), false);
  assert.equal(validate(profile({ ...said, origin: "guess" })), false);
  assert.equal(validate({ ...profile(said), owner: "Ania" }), false);
});
