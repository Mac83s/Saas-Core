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
  renderNavigation,
  renderPublishedPage,
  validateDesignTokens,
} from "./renderer";
export type * from "./types";
export {
  coreSectionTemplates,
  sectionIndustries,
  sectionTemplateBlock,
  availableSectionTemplates,
  replaceSectionLayout,
} from "./section-templates";
export type { SectionTemplate, CatalogLocale } from "./section-templates";

export {
  parseSiteAppearance,
  siteAppearanceClassName,
  siteGoogleFonts,
} from "./appearance";
export type { SiteAppearance } from "./appearance";
export {
  renderSiteHeader,
  renderSiteFooter,
  renderResponsiveNavigation,
} from "./site-chrome";

export { sectionDecorationPresets } from "./section-decoration-presets";
export type { SectionDecorationPreset } from "./section-decoration-presets";
export type { SeparatorV1Data } from "./separator-block";
