import business from "../../../../../../packages/contracts/page-templates/assets/business-studio.png";
import medicine from "../../../../../../packages/contracts/page-templates/assets/medicine-room.png";
import agriculture from "../../../../../../packages/contracts/page-templates/assets/agriculture-farm.png";
import electronics from "../../../../../../packages/contracts/page-templates/assets/electronics-workshop.png";
import {
  applySampleMedia,
  pageTemplateBlocks,
  sectionTemplateBlock,
  templatePreviewAssetId,
  type SectionTemplate,
  type PageTemplate,
  type BlockImageRenderer,
} from "@saas-core/site-blocks";
import { registry } from "./block-form";

const photos = { business, medicine, agriculture, electronics };

/** The blocks already carry `templatePreviewAssetId(i)` where binding `i`
 *  puts its photo (catalogue previews only, never a saved draft); this maps
 *  each of those ids to the bundled photo. */
function imageRendererFor(mediaIds: readonly string[]): BlockImageRenderer {
  const urls = new Map<string, string>();
  mediaIds.forEach((mediaId, index) => {
    const photo = photos[mediaId as keyof typeof photos];
    if (photo)
      urls.set(
        templatePreviewAssetId(index),
        typeof photo === "string" ? photo : photo.src,
      );
  });
  const imageRenderer: BlockImageRenderer = (image) => (
    // Local, bundled demonstration asset. Tenant images use PrivateMediaPreview.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={urls.get(image.asset_id)}
      alt={image.alt}
      loading="lazy"
      decoding="async"
    />
  );
  return imageRenderer;
}

export function sectionPreview(template: SectionTemplate, locale: "pl" | "en") {
  return {
    blocks: [
      applySampleMedia(
        sectionTemplateBlock(template, locale, registry),
        template,
        templatePreviewAssetId(0),
        locale,
      ),
    ],
    imageRenderer: imageRendererFor(
      template.sampleMedia ? [template.sampleMedia.id] : [],
    ),
  };
}

export function pageTemplatePreview(
  template: PageTemplate,
  locale: "pl" | "en",
) {
  return {
    blocks: pageTemplateBlocks(template, registry, locale),
    imageRenderer: imageRendererFor(
      (template.mediaBindings ?? []).map((binding) => binding.mediaId),
    ),
  };
}
