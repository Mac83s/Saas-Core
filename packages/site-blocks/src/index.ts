export const SITE_BLOCK_SCHEMA_VERSION = 1 as const;

export * from "./errors";
export { aiBadgeImageRenderer, withAiBadge } from "./ai-badge";
export {
  SITE_UI_LOCALES,
  siteUiTexts,
  type ContactFormTexts,
  type SiteUiLocale,
  type SiteUiTexts,
} from "./site-ui-texts";
export {
  isTemplateContact,
  withoutSlots,
  withoutTemplateLeftovers,
} from "./public-leftovers";
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
export { linkRel } from "./link-rel";
export { FULL_WIDTH, HALF_WIDTH, publicImage } from "./public-image";
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
  sampleMediaOf,
} from "./section-templates";
export type {
  SampleMedia,
  SectionTemplate,
  CatalogLocale,
} from "./section-templates";
export {
  fieldsOfOtherLayouts,
  hiddenFields,
  type HiddenField,
} from "./hidden-fields";
export {
  convertSection,
  coreSectionConversions,
  sectionConversions,
  type ConversionBlocker,
  type SectionConversion,
  type SectionConversionResult,
} from "./section-conversions";
export {
  composeTemplateSwap,
  keptSection,
  planTemplateSwap,
  type TemplateSwap,
  type TemplateSwapPlan,
} from "./template-swap";

export {
  pagePresentationClassName,
  parseSiteAppearance,
  siteAppearanceClassName,
  siteGoogleFonts,
} from "./appearance";
export type { SiteAppearance } from "./appearance";
export {
  renderArticleByline,
  renderLanguageSwitcher,
  renderSiteHeader,
  renderSiteFooter,
  renderResponsiveNavigation,
} from "./site-chrome";

export { sectionDecorationPresets } from "./section-decoration-presets";
export type { SectionDecorationPreset } from "./section-decoration-presets";
export type { SeparatorV1Data } from "./separator-block";
export {
  deadAnchorLinks,
  sampleData,
  unfilledPlaceholders,
  blockAssetIds,
  ensureUniqueAnchors,
  isRichTextAnchor,
  richTextAnchors,
  richTextAnchorSlug,
  setAtPath,
} from "./rich-text";
export type {
  DeadAnchorLink,
  SampleDataUse,
  UnfilledPlaceholder,
} from "./rich-text";
export { CYRILLIC_TO_LATIN, GERMAN_TO_LATIN } from "./transliteration";
