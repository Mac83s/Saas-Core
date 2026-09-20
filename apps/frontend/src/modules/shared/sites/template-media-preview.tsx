import business from "../../../../../../packages/contracts/page-templates/assets/business-studio.png";
import medicine from "../../../../../../packages/contracts/page-templates/assets/medicine-room.png";
import agriculture from "../../../../../../packages/contracts/page-templates/assets/agriculture-farm.png";
import electronics from "../../../../../../packages/contracts/page-templates/assets/electronics-workshop.png";
import {
  pageTemplateBlocks,
  sectionTemplateBlock,
  type SiteBlock,
  type SectionTemplate,
  type PageTemplate,
  type BlockImageRenderer,
} from "@saas-core/site-blocks";
import { registry } from "./block-form";

const photos = { business, medicine, agriculture, electronics };
// This sentinel exists in catalogue preview copies only, never in a saved draft.
const previewId = (index: number) =>
  `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
function preview(
  blocks: SiteBlock[],
  bindings: readonly {
    blockPosition: number;
    mediaId: string;
    alt: Record<"pl" | "en", string>;
  }[],
  locale: "pl" | "en",
) {
  const urls = new Map<string, string>();
  for (const [index, binding] of bindings.entries()) {
    const photo = photos[binding.mediaId as keyof typeof photos];
    if (!photo) continue;
    const id = previewId(index);
    urls.set(id, typeof photo === "string" ? photo : photo.src);
    blocks[binding.blockPosition].data.image = {
      asset_id: id,
      alt: binding.alt[locale],
    };
  }
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
  return { blocks, imageRenderer };
}
export function sectionPreview(template: SectionTemplate, locale: "pl" | "en") {
  return preview(
    [sectionTemplateBlock(template, locale, registry)],
    template.sampleMedia
      ? [
          {
            blockPosition: 0,
            mediaId: template.sampleMedia.id,
            alt: template.sampleMedia.alt,
          },
        ]
      : [],
    locale,
  );
}
export function pageTemplatePreview(
  template: PageTemplate,
  locale: "pl" | "en",
) {
  return preview(
    pageTemplateBlocks(template, registry, locale),
    template.mediaBindings ?? [],
    locale,
  );
}
