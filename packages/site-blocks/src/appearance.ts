import Ajv2020 from "ajv/dist/2020.js";
import schema from "@saas-core/contracts/site-blocks/site-appearance.v1.schema.json";
import schemaV2 from "@saas-core/contracts/site-blocks/site-appearance.v2.schema.json";
import tokensSchema from "@saas-core/contracts/site-blocks/design-tokens.v1.schema.json";
import pagePresentationSchema from "@saas-core/contracts/site-blocks/page-presentation.v1.schema.json";
import type { DesignTokensV1, PagePresentationV1 } from "./types";

export const siteGoogleFonts = {
  inter: "Inter",
  manrope: "Manrope",
  "dm-sans": "DM Sans",
  nunito: "Nunito",
  lora: "Lora",
  "playfair-display": "Playfair Display",
} as const;

export interface SiteAppearance {
  schemaVersion: 1 | 2;
  designTokens: DesignTokensV1;
  font:
    | "system"
    | "arial"
    | "georgia"
    | "trebuchet"
    | "verdana"
    | keyof typeof siteGoogleFonts;
  width: "narrow" | "standard" | "wide";
  buttons: "solid" | "outline" | "pill";
  header: {
    layout: "none" | "classic" | "centered" | "stacked";
    brand: string;
    tagline: string;
  };
  footer: {
    layout: "none" | "simple" | "centered" | "columns";
    text: string;
    links: { label: string; href: string }[];
  };
  navigation: { mobile: "drawer" | "bottom"; tablet: "drawer" | "bottom" };
}
const validate = new Ajv2020({ allErrors: true, strict: true })
  .addSchema(tokensSchema)
  .compile<SiteAppearance>({ anyOf: [schema, schemaV2] });
export function parseSiteAppearance(value: unknown): SiteAppearance {
  if (!validate(value)) throw new TypeError("Invalid site appearance");
  return value;
}
export function siteAppearanceClassName(value: SiteAppearance): string {
  parseSiteAppearance(value);
  return `site-appearance site-font--${value.font} site-width--${value.width} site-buttons--${value.buttons}`;
}

const validatePagePresentation = new Ajv2020({
  allErrors: true,
  strict: true,
}).compile<PagePresentationV1>(pagePresentationSchema);

/** Classes for one page's own presentation, set on the same `.site-theme`
 *  element as the site appearance. Absent means the page inherits it all. */
export function pagePresentationClassName(
  value: PagePresentationV1 | null | undefined,
): string {
  if (value === null || value === undefined) return "";
  if (!validatePagePresentation(value))
    throw new TypeError("Invalid page presentation");
  return [
    value.width === "full" ? "site-page--full" : "",
    value.headingFont ? `site-heading-font--${value.headingFont}` : "",
    value.bodyFont ? `site-body-font--${value.bodyFont}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}
