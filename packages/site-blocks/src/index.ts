export const SITE_BLOCK_SCHEMA_VERSION = 1 as const;

export * from "./errors";
export { coreSiteBlockManifest } from "./core-manifest";
export { CONTACT_FORM_FIELDS, contactFormFields } from "./contact-form-block";
export {
  availablePageTemplates,
  bindTemplateMedia,
  corePageTemplates,
  isRetiredPageTemplate,
  pageTemplateBlocks,
  templatePreviewAssetId,
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
  offeredSectionTemplates,
  sectionIndustries,
  sectionTemplateBlock,
  availableSectionTemplates,
  applySampleMedia,
  replaceSectionLayout,
} from "./section-templates";
export type { SectionTemplate, CatalogLocale } from "./section-templates";
export { hiddenFields, type HiddenField } from "./hidden-fields";

export {
  pagePresentationClassName,
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
export {
  unfilledPlaceholders,
  blockAssetIds,
  ensureUniqueAnchors,
  isRichTextAnchor,
  richTextAnchors,
  richTextAnchorSlug,
  setAtPath,
} from "./rich-text";
export type { UnfilledPlaceholder } from "./rich-text";
