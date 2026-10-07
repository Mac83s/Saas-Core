/** What a module's block types still owe the studio (ADR-077): the checks a
 *  product gets for the sets in its slot without writing a test of its own
 *  (`product-site-blocks.test.tsx`). `defineModuleSiteBlocks` already holds a
 *  set to its contract; these hold it to the panel — every name the studio
 *  prints has a message in both panel languages, and every section the
 *  library offers lands as a block its schema accepts. */

import {
  createSiteBlockRegistry,
  coreSiteBlockManifest,
  sectionTemplateBlock,
  type BlockFieldDefinition,
  type ModuleSiteBlocks,
} from "@saas-core/site-blocks";

type Messages = Record<string, unknown>;

function message(messages: Messages, key: string): unknown {
  return key
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        node !== null && typeof node === "object"
          ? (node as Messages)[part]
          : undefined,
      messages,
    );
}

/** The `Sites` keys the studio reads for a form: each field's label, each
 *  choice's options, and the same for the entries of a list. */
function fieldKeys(fields: readonly BlockFieldDefinition[]): string[] {
  return fields.flatMap((field) => [
    field.labelKey,
    ...(field.options ?? []).map(
      (option) => `${field.labelKey}Options.${option || "none"}`,
    ),
    ...fieldKeys(field.item ?? []),
  ]);
}

/** One line per thing wrong with a set; none when the studio can show it.
 *  `sites` is the `Sites` namespace of each panel language, the product's
 *  messages merged in. */
export function moduleBlockProblems(
  set: ModuleSiteBlocks,
  sites: Readonly<Record<"pl" | "en", Messages>>,
): string[] {
  const problems: string[] = [];
  const registry = createSiteBlockRegistry([
    coreSiteBlockManifest,
    set.manifest,
  ]);
  for (const block of set.manifest.blocks) {
    if (block.catalog === undefined) continue;
    for (const key of [
      block.catalog.labelKey,
      ...fieldKeys(block.catalog.fields),
    ])
      for (const locale of ["pl", "en"] as const)
        if (typeof message(sites[locale], key) !== "string")
          problems.push(`${block.type}: brak tekstu Sites.${key} (${locale})`);
  }
  for (const section of set.sectionTemplates)
    for (const locale of ["pl", "en"] as const)
      try {
        sectionTemplateBlock(section, locale, registry);
      } catch (error) {
        problems.push(
          `${section.id}: zalążek (${locale}) nie spełnia schematu — ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
  return problems;
}
