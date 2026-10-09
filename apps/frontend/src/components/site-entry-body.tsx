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
  > &
    Partial<Pick<PublicContentEntry, "cover">>;
  /**
   * Leaves out the picture the body opens with (`entry.cover`), for a page
   * that draws it itself — above the title, say. A body that does not open
   * with a picture is drawn whole.
   */
  withoutCover?: boolean;
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
export function SiteEntryBody({
  entry,
  withoutCover = false,
  designTokens,
  className,
}: Props) {
  const blocks = entry.blocks as unknown as SiteBlock[];
  return renderPublishedBody(
    {
      // The server says whether the body opens with a picture; which thing
      // of the body that is, is the same rule read the other way.
      blocks: withoutCover && entry.cover ? afterCover(blocks) : blocks,
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

/**
 * The body without the picture it opens with: the first thing of its first
 * block of text (`cover` in the read, `_cover` on the server), and the block
 * itself when the picture was all it held.
 */
function afterCover(blocks: SiteBlock[]): SiteBlock[] {
  const [first, ...rest] = blocks;
  const content = (first?.data as { content?: unknown } | undefined)?.content;
  if (!first || !Array.isArray(content)) return blocks;
  const left = content.slice(1);
  return left.length
    ? [{ ...first, data: { ...first.data, content: left } }, ...rest]
    : rest;
}
