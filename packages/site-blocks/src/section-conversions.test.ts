import { describe, expect, it } from "vitest";

import {
  convertSection,
  coreSectionConversions,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  offeredSectionTemplates,
  sectionConversions,
  sectionTemplateBlock,
  type SiteBlock,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const conversion = (id: string) =>
  coreSectionConversions().find((item) => item.id === id)!;
const list = (data: Record<string, unknown>): SiteBlock => ({
  block_type: "core.feature_list",
  schema_version: 5,
  data: { layout: "cards", ...data } as SiteBlock["data"],
});
const faq = (items: { question: string; answer: string }[]): SiteBlock => ({
  block_type: "core.faq",
  schema_version: 3,
  data: { title: "Pytania", layout: "accordion", items },
});

describe("the conversion contract", () => {
  it("repeats the target's own limits, layouts and fields", () => {
    for (const item of coreSectionConversions()) {
      const target = registry.definitions.get(item.to)!;
      const source = registry.definitions.get(item.from)!;
      const schemaOf = (definition: typeof target) =>
        definition.schemas.find(
          ({ version }) => version === definition.latestVersion,
        )!.schema as {
          properties: Record<
            string,
            {
              enum?: string[];
              maxItems?: number;
              items?: { properties: Record<string, { maxLength?: number }> };
            }
          >;
        };
      const to = schemaOf(target);
      const from = schemaOf(source);
      expect(to.properties.layout?.enum, item.id).toContain(item.layout);
      for (const [key, target_] of item.fields) {
        expect(from.properties[key], `${item.id} ${key}`).toBeDefined();
        expect(to.properties[target_], `${item.id} ${target_}`).toBeDefined();
      }
      if (item.items) {
        const targetList = to.properties[item.items.to]!;
        expect(targetList.maxItems, item.id).toBe(item.items.max);
        for (const [key, target_] of item.items.fields) {
          expect(
            from.properties[item.items.from]!.items!.properties[key],
            `${item.id} ${key}`,
          ).toBeDefined();
          expect(item.items.maxLength?.[target_], `${item.id} ${target_}`).toBe(
            targetList.items!.properties[target_]!.maxLength,
          );
        }
      }
    }
  });

  it("offers each pair only from its own type", () => {
    expect(
      sectionConversions("core.feature_list", registry).map(({ id }) => id),
    ).toEqual(["feature_list_to_faq", "feature_list_to_rich_text"]);
    expect(sectionConversions("core.hero", registry)).toEqual([]);
  });
});

describe("a list", () => {
  it("becomes questions and answers, marking the answers it lacks", () => {
    const result = convertSection(
      list({
        title: "Co warto wiedzieć",
        lead: "Krótko o zasadach",
        items: [
          { title: "Ile to trwa?", text: "Około godziny." },
          { title: "Czy trzeba się przygotować?" },
        ],
      }),
      conversion("feature_list_to_faq"),
      registry,
      "pl",
    );
    expect(result.blockers).toEqual([]);
    expect(result.block?.data).toEqual({
      layout: "accordion",
      title: "Co warto wiedzieć",
      items: [
        { question: "Ile to trwa?", answer: "Około godziny." },
        {
          question: "Czy trzeba się przygotować?",
          answer: "[Uzupełnij: odpowiedź]",
        },
      ],
    });
    expect(result.filled).toBe(1);
    expect(result.lost.map(({ field }) => field.labelKey)).toEqual(["lead"]);
  });

  it("becomes text with a heading per item and its note kept", () => {
    const result = convertSection(
      list({
        title: "Jak przebiega wizyta",
        items: [
          { title: "Rozmowa", text: "Poznajemy potrzeby.", group: "Start" },
          { title: "Rozmowa", text: "Ustalamy termin." },
        ],
        note: { title: "Ważne", text: "Weź dokumenty." },
      }),
      conversion("feature_list_to_rich_text"),
      registry,
      "pl",
    );
    expect(result.blockers).toEqual([]);
    expect(result.block?.data.content).toEqual([
      { type: "heading", level: 3, anchor: "rozmowa", text: "Rozmowa" },
      { type: "paragraph", content: [{ text: "Poznajemy potrzeby." }] },
      { type: "heading", level: 3, anchor: "rozmowa-2", text: "Rozmowa" },
      { type: "paragraph", content: [{ text: "Ustalamy termin." }] },
      {
        type: "note",
        tone: "info",
        title: "Ważne",
        content: [{ text: "Weź dokumenty." }],
      },
    ]);
    expect(
      result.lost.map(({ field, parent }) =>
        [parent?.labelKey, field.labelKey].filter(Boolean).join("."),
      ),
    ).toEqual(["featureItems.itemGroup"]);
  });
});

describe("questions and answers", () => {
  it("say which item stops the change to a list", () => {
    const long = faq([
      { question: "Krótko?", answer: "Tak." },
      { question: "P".repeat(150), answer: "Za długie pytanie." },
    ]);
    const result = convertSection(
      long,
      conversion("faq_to_feature_list"),
      registry,
      "en",
    );
    expect(result.block).toBeNull();
    expect(result.blockers).toEqual([
      { kind: "tooLong", item: 1, field: "question", max: 120 },
    ]);
    const many = faq(
      Array.from({ length: 20 }, (_, index) => ({
        question: `Pytanie ${index}`,
        answer: "Odpowiedź",
      })),
    );
    expect(
      convertSection(many, conversion("faq_to_feature_list"), registry, "pl")
        .blockers,
    ).toEqual([{ kind: "tooMany", count: 20, max: 16 }]);
  });

  it("keep the section's look envelope when they become text", () => {
    const block: SiteBlock = {
      ...faq([
        { question: "Czy dojeżdżacie?", answer: "Tak, w promieniu 50 km." },
      ]),
      presentation: { schemaVersion: 2, anchor: "pytania" },
    };
    const result = convertSection(
      block,
      conversion("faq_to_rich_text"),
      registry,
      "pl",
    );
    expect(result.block?.presentation).toEqual({
      schemaVersion: 2,
      anchor: "pytania",
    });
    expect(result.lost).toEqual([]);
  });
});

it("a section still being filled in is not converted, and nothing throws", () => {
  const empty: SiteBlock = {
    block_type: "core.faq",
    schema_version: 3,
    data: { layout: "accordion", items: [{ question: "", answer: "" }] },
  };
  expect(
    convertSection(empty, conversion("faq_to_rich_text"), registry, "pl"),
  ).toEqual({
    block: null,
    lost: [],
    filled: 0,
    blockers: [{ kind: "invalid" }],
  });
});

it("every library section of a convertible type converts or says why not", () => {
  const problems: string[] = [];
  for (const template of offeredSectionTemplates())
    for (const item of sectionConversions(template.blockType, registry))
      for (const locale of ["pl", "en"] as const) {
        const result = convertSection(
          sectionTemplateBlock(template, locale, registry),
          item,
          registry,
          locale,
        );
        if (result.blockers.some(({ kind }) => kind === "invalid"))
          problems.push(`${template.id} → ${item.to} ${locale}`);
      }
  expect(problems).toEqual([]);
});
