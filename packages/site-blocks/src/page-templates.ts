import businessStudio from "@saas-core/contracts/page-templates/core.business_studio.v1.json";
import electronicsService from "@saas-core/contracts/page-templates/core.electronics_service.v1.json";
import agricultureServices from "@saas-core/contracts/page-templates/core.agriculture_services.v1.json";
import medicineClinic from "@saas-core/contracts/page-templates/core.medicine_clinic.v1.json";
import serviceLandingV1 from "@saas-core/contracts/page-templates/core.service_landing.v2.json";
import companyV1 from "@saas-core/contracts/page-templates/core.company.v2.json";
import profileV1 from "@saas-core/contracts/page-templates/core.profile.v2.json";
import specialistLandingV1 from "@saas-core/contracts/page-templates/core.specialist_landing.v2.json";
import productFirstImpression from "@saas-core/contracts/page-templates/core.product_first_impression.v2.json";
import serviceGuide from "@saas-core/contracts/page-templates/core.service_guide.v2.json";
import expertKnowledge from "@saas-core/contracts/page-templates/core.expert_knowledge.v2.json";
import productFullStory from "@saas-core/contracts/page-templates/core.product_full_story.v1.json";
import technicalB2b from "@saas-core/contracts/page-templates/core.technical_b2b.v1.json";
import serviceFocused from "@saas-core/contracts/page-templates/core.service_focused.v1.json";
import premiumService from "@saas-core/contracts/page-templates/core.premium_service.v1.json";
import studioManifesto from "@saas-core/contracts/page-templates/core.studio_manifesto.v1.json";
import caseStudy from "@saas-core/contracts/page-templates/core.case_study.v1.json";
import templateManifest from "@saas-core/contracts/page-templates/manifest.json";

import { InvalidPageTemplateError } from "./errors";
import { setAtPath } from "./rich-text";
import type {
  BlockRegistry,
  PageTemplate,
  SiteBlock,
  TemplateMediaBinding,
} from "./types";

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
  medicineClinic as unknown as PageTemplate,
  agricultureServices as unknown as PageTemplate,
  electronicsService as unknown as PageTemplate,
  businessStudio as unknown as PageTemplate,
  productFirstImpression as unknown as PageTemplate,
  serviceGuide as unknown as PageTemplate,
  expertKnowledge as unknown as PageTemplate,
  productFullStory as unknown as PageTemplate,
  technicalB2b as unknown as PageTemplate,
  serviceFocused as unknown as PageTemplate,
  premiumService as unknown as PageTemplate,
  studioManifesto as unknown as PageTemplate,
  caseStudy as unknown as PageTemplate,
];

const retired = new Set(
  templateManifest.templates
    .filter((entry) => (entry as { retired?: boolean }).retired === true)
    .map((entry) => entry.id),
);

/** A retired recipe stays importable by id and its pages stay as they are,
 *  but galleries and the blueprint catalogue no longer offer it. */
export function isRetiredPageTemplate(id: string): boolean {
  return retired.has(id);
}

/** Recipes are seed content, not a second content model: applying one produces
 *  ordinary blocks that go through the same draft save, validation and
 *  versioning as anything typed by hand (ADR-031). */
export function corePageTemplates(): readonly PageTemplate[] {
  return recipes;
}

/** Stand-in asset id for a template's photo in catalogue previews and
 *  validation. It never reaches a saved draft: importing a recipe replaces
 *  it with the materialized asset. */
export function templatePreviewAssetId(index: number): string {
  return `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** Puts each binding's photo into its block: `{asset_id, alt}` at `path`
 *  (absent: `["image"]`), under the recipe rules of `setAtPath`. Returns
 *  copies; a block no binding touches is returned as is. */
export function bindTemplateMedia(
  blocks: readonly SiteBlock[],
  bindings: readonly TemplateMediaBinding[],
  assetIdFor: (bindingIndex: number, mediaId: string) => string,
  locale: "pl" | "en",
): SiteBlock[] {
  const result = [...blocks];
  const copied = new Set<number>();
  bindings.forEach((binding, index) => {
    const block = result[binding.blockPosition];
    if (block === undefined)
      throw new TypeError(`Brak bloku ${binding.blockPosition} dla zdjęcia.`);
    if (!copied.has(binding.blockPosition)) {
      result[binding.blockPosition] = {
        ...block,
        data: structuredClone(block.data),
      };
      copied.add(binding.blockPosition);
    }
    setAtPath(result[binding.blockPosition]!.data, binding.path ?? ["image"], {
      asset_id: assetIdFor(index, binding.mediaId),
      alt: binding.alt[locale],
    });
  });
  return result;
}

/** Blocks a template would seed, validated against the live registry first.
 *  A deployment can be missing a block a recipe names — a vertical that ships
 *  its own manifest, an entitlement that hides a module — and finding that out
 *  when the draft fails to save is far too late. Photos are bound with
 *  `templatePreviewAssetId`, so a block that needs its picture validates. */
export function pageTemplateBlocks(
  template: PageTemplate,
  registry: BlockRegistry,
  locale: "pl" | "en" = "pl",
): SiteBlock[] {
  let seeded = (
    locale === "en"
      ? (template.localizedBlocks?.en ?? template.blocks)
      : template.blocks
  ).map((block): SiteBlock => ({
    block_type: block.block_type,
    schema_version: block.schema_version,
    data: structuredClone(block.data),
    ...(block.decoration
      ? { decoration: structuredClone(block.decoration) }
      : {}),
    ...(block.presentation
      ? { presentation: structuredClone(block.presentation) }
      : {}),
  }));
  (template.mediaBindings ?? []).forEach((binding, index) => {
    try {
      seeded = bindTemplateMedia(
        seeded,
        [binding],
        () => templatePreviewAssetId(index),
        locale,
      );
    } catch (cause) {
      throw new InvalidPageTemplateError(
        template.id,
        binding.blockPosition,
        cause,
      );
    }
  });
  seeded.forEach((block, index) => {
    try {
      registry.validate(block);
    } catch (cause) {
      throw new InvalidPageTemplateError(template.id, index, cause);
    }
  });
  return seeded;
}

/** Templates this deployment can actually apply and still offers: not
 *  retired, every block is registered and every entitlement is granted. */
export function availablePageTemplates(
  registry: BlockRegistry,
  entitlements: readonly string[],
  templates: readonly PageTemplate[] = recipes,
): readonly PageTemplate[] {
  const granted = new Set(entitlements);
  return templates.filter((template) => {
    if (isRetiredPageTemplate(template.id)) return false;
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
