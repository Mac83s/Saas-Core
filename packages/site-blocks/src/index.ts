export const SITE_BLOCK_SCHEMA_VERSION = 1 as const;

export * from "./errors";
export { coreSiteBlockManifest } from "./core-manifest";
export {
  availablePageTemplates,
  corePageTemplates,
  pageTemplateBlocks,
} from "./page-templates";
export { createSiteBlockRegistry, defineSiteBlockManifest } from "./registry";
export {
  designTokenClassName,
  renderDraftPreview,
  renderPublishedPage,
  validateDesignTokens,
} from "./renderer";
export type * from "./types";
