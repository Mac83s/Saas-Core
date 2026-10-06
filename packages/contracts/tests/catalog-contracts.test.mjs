import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const contractRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

async function readJson(...segments) {
  return JSON.parse(
    await readFile(path.join(contractRoot, ...segments), "utf8"),
  );
}

// The towns published before the directory took every town of Poland, by
// their TERYT ids. A slug is a segment of a public address: these never move,
// and neither does any slug a later refresh finds in the file.
const PUBLISHED_FIRST = {
  mragowo: "0964896",
  olsztyn: "0964465",
  elk: "0977670",
  gizycko: "0977692",
  ketrzyn: "0964710",
  szczytno: "0964991",
  ostroda: "0964927",
  ilawa: "0964650",
  elblag: "0932703",
  bartoszyce: "0964583",
  braniewo: "0932710",
  "lidzbark-warminski": "0964732",
  nidzica: "0964904",
  pisz: "0977835",
  wegorzewo: "0977947",
  olecko: "0977798",
  goldap: "0977700",
  dzialdowo: "0930609",
  mikolajki: "0977723",
  "ruciane-nida": "0977841",
  ryn: "0977893",
  orzysz: "0977806",
  "biala-piska": "0977640",
  olsztynek: "0964910",
  morag: "0964850",
  lubawa: "0964749",
  "nowe-miasto-lubawskie": "0983563",
  biskupiec: "0964590",
  reszel: "0964979",
  "dobre-miasto": "0964614",
  frombork: "0932732",
  tolkmicko: "0933000",
  pasym: "0485813",
  barczewo: "0964577",
  lidzbark: "0930644",
  warszawa: "0918123",
  krakow: "0950463",
  lodz: "0957650",
  wroclaw: "0986283",
  poznan: "0969400",
  gdansk: "0933016",
  gdynia: "0934100",
  szczecin: "0977976",
  bydgoszcz: "0928363",
  torun: "0982724",
  lublin: "0954700",
  bialystok: "0922410",
  katowice: "0937474",
  rzeszow: "0974133",
  kielce: "0945930",
  opole: "0965016",
  "zielona-gora": "0988313",
  "gorzow-wielkopolski": "0935140",
};

const VOIVODESHIPS = new Set([
  "dolnośląskie",
  "kujawsko-pomorskie",
  "lubelskie",
  "lubuskie",
  "łódzkie",
  "małopolskie",
  "mazowieckie",
  "opolskie",
  "podkarpackie",
  "podlaskie",
  "pomorskie",
  "śląskie",
  "świętokrzyskie",
  "warmińsko-mazurskie",
  "wielkopolskie",
  "zachodniopomorskie",
]);

test("the towns name their source and are as many as it says", async () => {
  const { source, cities } = await readJson("catalog", "cities.json");
  assert.match(source.register, /PRNG/);
  assert.match(source.exported, /^\d{4}-\d{2}-\d{2}$/);
  assert.match(source.terytStateOn, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(cities.length, source.count);
  assert.ok(cities.length > 1000, "every town of Poland, not a chosen few");
});

test("every town is one address in one region, inside Poland", async () => {
  const { cities } = await readJson("catalog", "cities.json");
  for (const key of ["slug", "teryt"])
    assert.equal(
      new Set(cities.map((city) => city[key])).size,
      cities.length,
      `${key} repeats`,
    );
  // A name two towns share is told apart by the region.
  assert.equal(
    new Set(cities.map((city) => `${city.name}|${city.voivodeship}`)).size,
    cities.length,
  );
  for (const city of cities) {
    assert.match(city.slug, /^[a-z]+(-[a-z]+)*$/, city.name);
    assert.match(city.teryt, /^\d{7}$/, city.name);
    assert.ok(VOIVODESHIPS.has(city.voivodeship), city.name);
    assert.ok(city.lat > 49 && city.lat < 54.9, `${city.name}: latitude`);
    assert.ok(city.lng > 14.1 && city.lng < 24.2, `${city.name}: longitude`);
  }
});

test("a published town keeps its slug", async () => {
  const { cities } = await readJson("catalog", "cities.json");
  const bySlug = new Map(cities.map((city) => [city.slug, city]));
  for (const [slug, teryt] of Object.entries(PUBLISHED_FIRST))
    assert.equal(bySlug.get(slug)?.teryt, teryt, slug);
  // The pilot's town (handoff 06.10), and both towns of a shared name.
  assert.equal(bySlug.get("lomza")?.name, "Łomża");
  assert.equal(bySlug.get("olsztyn").voivodeship, "warmińsko-mazurskie");
  assert.equal(bySlug.get("olsztyn-slaskie").voivodeship, "śląskie");
});

test("the manifest keeps the categories and leaves the towns to their file", async () => {
  const manifest = await readJson("catalog", "manifest.json");
  assert.equal(manifest.schemaVersion, 2);
  assert.equal(manifest.cities, undefined);
  assert.ok(manifest.categories.business.length > 0);
});
