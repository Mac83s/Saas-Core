import catalog from "@saas-core/contracts/site-blocks/section-templates.v1.json";

import type { BlockRegistry, JsonObject, SiteBlock } from "./types";

export type SectionTemplate = (typeof catalog.templates)[number];
export type CatalogLocale = "pl" | "en";

/** Versioned seed content only. Published blocks never consult this catalog. */
export function coreSectionTemplates(): readonly SectionTemplate[] {
  return catalog.templates;
}

export function sectionIndustries() {
  return catalog.industries;
}

export function sectionTemplateBlock(
  template: SectionTemplate,
  locale: CatalogLocale,
  registry: BlockRegistry,
): SiteBlock {
  const block = {
    block_type: template.blockType,
    schema_version: template.schemaVersion,
    data: structuredClone(template.seed[locale]) as unknown as JsonObject,
  };
  registry.validate(block);
  return block;
}

/** Industry is a preference, never an entitlement. Universal choices remain. */
export function availableSectionTemplates(
  registry: BlockRegistry,
  context: {
    entitlements: readonly string[];
    modules: readonly string[];
    industry?: string;
    blockType?: string;
  },
): readonly SectionTemplate[] {
  return catalog.templates.filter((template) => {
    if (context.blockType && template.blockType !== context.blockType)
      return false;
    if (
      context.industry &&
      template.industries.length > 0 &&
      !template.industries.some((industry) => industry === context.industry)
    )
      return false;
    if (
      template.requirements.requiredEntitlements.some(
        (key) => !context.entitlements.includes(key),
      )
    )
      return false;
    if (
      template.requirements.requiredModules.some(
        (key) => !context.modules.includes(key),
      )
    )
      return false;
    try {
      sectionTemplateBlock(template, "pl", registry);
      sectionTemplateBlock(template, "en", registry);
      return true;
    } catch {
      return false;
    }
  });
}

/** Replace presentation only. Never copy seed text over the user's content. */
export function replaceSectionLayout(
  block: SiteBlock,
  template: SectionTemplate,
  registry: BlockRegistry,
): SiteBlock {
  if (block.block_type !== template.blockType) {
    throw new Error(
      "Section layouts can only be replaced within the same block type.",
    );
  }
  const migrated = registry.migrate(block);
  const replacement = {
    ...migrated,
    data: { ...migrated.data, layout: template.layout },
  };
  registry.validate(replacement);
  return replacement;
}
