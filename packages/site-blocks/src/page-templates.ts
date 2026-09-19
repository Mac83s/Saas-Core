import serviceLandingV1 from "@saas-core/contracts/page-templates/core.service_landing.v1.json";
import companyV1 from "@saas-core/contracts/page-templates/core.company.v1.json";
import profileV1 from "@saas-core/contracts/page-templates/core.profile.v1.json";
import specialistLandingV1 from "@saas-core/contracts/page-templates/core.specialist_landing.v1.json";

import { InvalidPageTemplateError } from "./errors";
import type { BlockRegistry, PageTemplate, SiteBlock } from "./types";

/** TypeScript infers a union with `undefined` for each recipe's optional block
 *  properties, which does not fit `JsonObject`. The shape is guaranteed at run
 *  time instead: the contract tests validate every recipe against the recipe
 *  schema and every seeded block against its canonical block schema, and
 *  `pageTemplateBlocks` re-checks against the live registry before use. */
const recipes: readonly PageTemplate[] = [
  profileV1 as unknown as PageTemplate,
  specialistLandingV1 as unknown as PageTemplate,
  companyV1 as unknown as PageTemplate,
  serviceLandingV1 as unknown as PageTemplate,
];

/** Recipes are seed content, not a second content model: applying one produces
 *  ordinary blocks that go through the same draft save, validation and
 *  versioning as anything typed by hand (ADR-031). */
export function corePageTemplates(): readonly PageTemplate[] {
  return recipes;
}

/** Blocks a template would seed, validated against the live registry first.
 *  A deployment can be missing a block a recipe names — a vertical that ships
 *  its own manifest, an entitlement that hides a module — and finding that out
 *  when the draft fails to save is far too late. */
export function pageTemplateBlocks(
  template: PageTemplate,
  registry: BlockRegistry,
): SiteBlock[] {
  return template.blocks.map((block, index) => {
    const seeded: SiteBlock = {
      block_type: block.block_type,
      schema_version: block.schema_version,
      data: structuredClone(block.data),
    };
    try {
      registry.validate(seeded);
    } catch (cause) {
      throw new InvalidPageTemplateError(template.id, index, cause);
    }
    return seeded;
  });
}

/** Templates this deployment can actually apply: every block is registered and
 *  every entitlement is granted. */
export function availablePageTemplates(
  registry: BlockRegistry,
  entitlements: readonly string[],
  templates: readonly PageTemplate[] = recipes,
): readonly PageTemplate[] {
  const granted = new Set(entitlements);
  return templates.filter((template) => {
    if (
      (template.requiredEntitlements ?? []).some(
        (entitlement) => !granted.has(entitlement),
      )
    ) {
      return false;
    }
    try {
      pageTemplateBlocks(template, registry);
      return true;
    } catch {
      return false;
    }
  });
}
