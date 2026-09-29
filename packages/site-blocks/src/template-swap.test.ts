import { describe, expect, it } from "vitest";

import {
  composeTemplateSwap,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  keptSection,
  pageTemplateBlocks,
  planTemplateSwap,
  richTextAnchors,
  type PageTemplate,
  type SiteBlock,
} from "./index";
import { availablePageTemplates, corePageTemplates } from "./page-templates";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

const hero = (title: string, layout = "classic"): SiteBlock => ({
  block_type: "core.hero",
  schema_version: 6,
  data: { title, layout },
});
const list = (title: string, layout: string): SiteBlock => ({
  block_type: "core.feature_list",
  schema_version: 5,
  data: { title, layout, items: [{ title: "A", text: "a" }] },
});
const faq = (title: string): SiteBlock => ({
  block_type: "core.faq",
  schema_version: 3,
  data: {
    title,
    layout: "accordion",
    items: [{ question: "Q?", answer: "A." }],
  },
});
const incoming = (...blocks: SiteBlock[]): SiteBlock[] => blocks;

describe("template swap plan", () => {
  it("keeps sections of the same type in the template's order and names the rest", () => {
    const plan = planTemplateSwap(
      [faq("Pytania"), hero("Nasza firma"), list("Oferta", "cards")],
      incoming(
        hero("Szablon"),
        list("Lista", "cards"),
        faq("FAQ"),
        hero("Drugie"),
      ),
    );
    expect(plan.slots).toEqual([1, 2, 0, null]);
    expect(plan.unplaced).toEqual([]);
  });

  it("never moves content across block types", () => {
    const plan = planTemplateSwap(
      [faq("Pytania"), list("Oferta", "cards")],
      incoming(hero("Szablon")),
    );
    expect(plan.slots).toEqual([null]);
    expect(plan.unplaced).toEqual([0, 1]);
  });

  it("prefers the section with the same role when a type has several", () => {
    // Both are lists; the catalogue gives the preparation layout the
    // reassurance role and cards the offer role.
    const reassurance = list("Przygotowanie", "prep_stages");
    const offer = list("Oferta", "cards");
    const plan = planTemplateSwap(
      [reassurance, offer],
      incoming(
        list("Co robimy", "cards"),
        list("Jak się przygotować", "prep_stages"),
      ),
    );
    expect(plan.slots).toEqual([1, 0]);
  });
});

describe("kept sections", () => {
  it("keep the page's text in the template's look", () => {
    const mine = hero("Opieka weterynaryjna w gospodarstwie", "classic");
    const theirs: SiteBlock = {
      ...hero("Szablon", "split"),
      presentation: { schemaVersion: 2, inner: "wide", anchor: "start" },
    };
    const kept = keptSection(mine, theirs, registry);
    expect(kept.data).toMatchObject({
      title: "Opieka weterynaryjna w gospodarstwie",
      layout: "split",
    });
    expect(kept.presentation).toEqual({
      schemaVersion: 2,
      inner: "wide",
      anchor: "start",
    });
  });

  it("stay unique on the page: the template's anchors win", () => {
    const mine: SiteBlock = {
      block_type: "core.rich_text",
      schema_version: 4,
      data: {
        layout: "column",
        content: [
          { type: "heading", level: 2, anchor: "kontakt", text: "Kontakt" },
          {
            type: "paragraph",
            content: [{ text: "Zobacz", href: "#kontakt" }],
          },
        ],
      },
    };
    const text = (anchor: string): SiteBlock => ({
      block_type: "core.rich_text",
      schema_version: 4,
      data: {
        layout: "column",
        content: [{ type: "paragraph", content: [{ text: "Szablon" }] }],
      },
      presentation: { schemaVersion: 2, anchor },
    });
    const sections = incoming(text("o-nas"), text("kontakt"));
    const plan = planTemplateSwap([mine], sections);
    const swap = composeTemplateSwap([mine], sections, plan, registry, true);
    expect(swap.kept).toHaveLength(1);
    const kept = swap.kept[0]!.block;
    expect(kept.presentation).toEqual({ schemaVersion: 2, anchor: "o-nas" });
    const content = kept.data.content as {
      anchor?: string;
      content?: { href?: string }[];
    }[];
    expect(content[0]!.anchor).not.toBe("kontakt");
    expect(content[1]!.content![0]!.href).toBe(`#${content[0]!.anchor}`);
  });

  it("left without a place are added only on request", () => {
    const sections = incoming(hero("Szablon"));
    const current = [hero("Mój"), faq("Pytania")];
    const plan = planTemplateSwap(current, sections);
    expect(
      composeTemplateSwap(current, sections, plan, registry, false).appended,
    ).toEqual([]);
    expect(
      composeTemplateSwap(current, sections, plan, registry, true).appended,
    ).toHaveLength(1);
  });
});

describe("every offered page template", () => {
  const templates = availablePageTemplates(registry, ["sites.enabled"]);
  const sections = (template: PageTemplate, locale: "pl" | "en") =>
    pageTemplateBlocks(template, registry, locale);

  it("takes a page built from any other one with nothing invalid and anchors unique", () => {
    const problems: string[] = [];
    for (const from of templates)
      for (const to of templates)
        for (const locale of ["pl", "en"] as const) {
          const page = pageTemplateBlocks(from, registry, locale).map((block) =>
            registry.migrate(block),
          );
          const target = sections(to, locale);
          const plan = planTemplateSwap(page, target);
          const swap = composeTemplateSwap(page, target, plan, registry, true);
          const final = [...target];
          for (const { slot, block } of swap.kept) final[slot] = block;
          final.push(...swap.appended);
          try {
            final.forEach((block) => registry.validate(block));
          } catch (error) {
            problems.push(`${from.id} → ${to.id} ${locale}: ${String(error)}`);
          }
          const anchors = richTextAnchors(final);
          if (new Set(anchors).size !== anchors.length)
            problems.push(`${from.id} → ${to.id} ${locale}: ${anchors}`);
          // Nothing of the page is dropped without the choice to add it.
          expect(swap.kept.length + swap.appended.length).toBe(page.length);
        }
    expect(problems).toEqual([]);
  });

  it("keeps a page's sections when it takes its own template back", () => {
    for (const template of corePageTemplates()) {
      if (!templates.includes(template)) continue;
      const page = pageTemplateBlocks(template, registry, "pl").map((block) =>
        registry.migrate(block),
      );
      const plan = planTemplateSwap(page, sections(template, "pl"));
      expect(plan.slots).toEqual(page.map((_, index) => index));
    }
  });
});
