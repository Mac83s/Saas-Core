import catalog from "@saas-core/contracts/site-blocks/section-templates.v7.json";

import { setAtPath } from "./rich-text";

import type {
  BlockRegistry,
  ConversionStage,
  JsonObject,
  SiteBlock,
} from "./types";

export interface SampleMedia {
  id: string;
  alt: Record<"pl" | "en", string>;
  /** v5: where `{asset_id, alt}` goes in the seed. Absent: `["image"]`. */
  path?: readonly (string | number)[];
}

export interface SectionTemplate {
  id: string;
  version: number;
  blockType: string;
  schemaVersion: number;
  layout: string;
  kind: "default" | "industry";
  industries: readonly string[];
  labels: Record<
    "pl" | "en",
    { name: string; description: string; usage: string }
  >;
  goals: readonly string[];
  composition: {
    role: string;
    preferredPosition: string;
    recommendedNext: readonly string[];
    repeatable: boolean;
  };
  requirements: {
    requiredEntitlements: readonly string[];
    requiredModules: readonly string[];
    media: string;
  };
  /** One sample photo, or — v7, from the first gallery (F4-P3) — a list,
   *  each photo with its own path. `sampleMediaOf` reads either. */
  sampleMedia?: SampleMedia | readonly SampleMedia[];
  /** v5 ranking metadata. Preferences for the library, never restrictions. */
  contentProfiles?: readonly ("S" | "M" | "L" | "XL")[];
  readingPattern?: "linear" | "scan" | "reference" | "visual";
  styleAffinities?: readonly string[];
  supportedWidths?: readonly ("narrow" | "standard" | "wide" | "full")[];
  targetSurface?: readonly ("page" | "entry")[];
  /** v6, required for every template added from v6 on: where the section
   *  sits on the visitor's path and whether it carries the primary action. */
  conversion?: { stage: ConversionStage; primaryAction: boolean };
  seed: Record<"pl" | "en", JsonObject>;
}
const templates = catalog.templates as unknown as readonly SectionTemplate[];
const newest = new Map<string, SectionTemplate>();
for (const template of templates)
  if ((newest.get(template.id)?.version ?? 0) < template.version)
    newest.set(template.id, template);
// A newer version takes the place of the first one: the library keeps its
// order when a template is revised.
const offered = [...new Set(templates.map((template) => template.id))].map(
  (id) => newest.get(id)!,
);
export type CatalogLocale = "pl" | "en";

/** Versioned seed content only. Published blocks never consult this catalog.
 *  Every version of every template, including ones a newer version replaced. */
export function coreSectionTemplates(): readonly SectionTemplate[] {
  return templates;
}

/** What the library and the layout switch offer: the newest version of each
 *  template, where the template first appeared. Older versions stay in the
 *  catalogue for history and tests. */
export function offeredSectionTemplates(): readonly SectionTemplate[] {
  return offered;
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

/** The template's sample photos as a list, whichever way it gives them. */
export function sampleMediaOf(
  template: SectionTemplate,
): readonly SampleMedia[] {
  const sample = template.sampleMedia;
  if (sample === undefined) return [];
  return Array.isArray(sample) ? sample : [sample as SampleMedia];
}

/** The section's sample photos in a copy of the block, each at its `path`.
 *  `assetId` is the one asset of a single photo, or — for several — the
 *  asset for a photo's id and position. Without sample photos: the block. */
export function applySampleMedia(
  block: SiteBlock,
  template: SectionTemplate,
  assetId: string | ((mediaId: string, index: number) => string),
  locale: CatalogLocale,
): SiteBlock {
  const samples = sampleMediaOf(template);
  if (samples.length === 0) return block;
  const data = structuredClone(block.data);
  samples.forEach((sample, index) =>
    setAtPath(data, sample.path ?? ["image"], {
      asset_id:
        typeof assetId === "string" ? assetId : assetId(sample.id, index),
      alt: sample.alt[locale],
    }),
  );
  return { ...block, data };
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
  return offered.filter((template) => {
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
