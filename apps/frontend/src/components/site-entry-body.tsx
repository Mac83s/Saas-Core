import type { PublicContentEntry } from "@saas-core/api-client";
import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedBody,
  type DesignTokensV1,
  type SiteBlock,
} from "@saas-core/site-blocks";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

type Props = {
  /** An entry as `contentEntry` returned it. */
  entry: Pick<
    PublicContentEntry,
    "blocks" | "locale" | "image_sizes" | "ai_media_ids" | "machine_text"
  >;
  /** The theme the blocks are drawn in; the core's default when left out. */
  designTokens?: DesignTokensV1;
  /** Added to the wrapper, for the product's own stylesheet. */
  className?: string;
};

/**
 * The body of an entry of the platform's own content, drawn with the core's
 * block components inside a product's own page (ADR-079 pkt 30): the blocks
 * and nothing around them — no header, menu, footer, `<main>` or title; the
 * product's layout and page are those.
 *
 * Pictures load from `/media/…` on the platform's host with their stored
 * size and the AI badge; a version a machine translated and nobody accepted
 * says so above the text. A contact form and blocks of a company's live
 * records are left out: there is no company site behind this page.
 *
 * The blocks' styles are part of `@saas-core/ui/globals.css`, written under
 * `.site-theme`; the wrapper is `.site-theme.site-theme--embedded`, which
 * takes its height, background, colour and font from the page around it.
 * A server component; it needs no provider.
 */
export function SiteEntryBody({ entry, designTokens, className }: Props) {
  return renderPublishedBody(
    {
      blocks: entry.blocks as unknown as SiteBlock[],
      locale: entry.locale,
      // The server's verdict: AI text nobody accepted, the operator's switch on.
      machineNotice: entry.machine_text?.notice === true,
      imageSizes: entry.image_sizes,
      aiMediaIds: entry.ai_media_ids,
      designTokens,
      className,
    },
    registry,
  );
}
