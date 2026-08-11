import { createElement, type ReactElement } from "react";

import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import designTokensSchema from "@saas-core/contracts/site-blocks/design-tokens.v1.schema.json";

import { InvalidDesignTokensError } from "./errors";
import type {
  BlockRegistry,
  DesignTokensV1,
  DraftPreviewDocument,
  PublishedPageDocument,
  SiteBlock,
} from "./types";

const validateTokens = new Ajv2020({ allErrors: true, strict: true }).compile(
  designTokensSchema,
);

const themeClasses = {
  palette: {
    neutral: "site-theme--neutral",
    blue: "site-theme--blue",
    emerald: "site-theme--emerald",
  },
  typography: { sans: "site-theme--sans", serif: "site-theme--serif" },
  radius: {
    none: "site-theme--radius-none",
    small: "site-theme--radius-small",
    medium: "site-theme--radius-medium",
    large: "site-theme--radius-large",
  },
  spacing: {
    compact: "site-theme--compact",
    comfortable: "site-theme--comfortable",
    spacious: "site-theme--spacious",
  },
} as const;

function tokenErrors(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map(
    (error) => `${error.instancePath || "/"} ${error.message ?? "invalid"}`,
  );
}

export function validateDesignTokens(tokens: DesignTokensV1): void {
  if (!validateTokens(tokens)) {
    throw new InvalidDesignTokensError(tokenErrors(validateTokens.errors));
  }
}

export function designTokenClassName(tokens: DesignTokensV1): string {
  validateDesignTokens(tokens);
  return [
    "site-theme",
    themeClasses.palette[tokens.palette],
    themeClasses.typography[tokens.typography],
    themeClasses.radius[tokens.radius],
    themeClasses.spacing[tokens.spacing],
  ].join(" ");
}

function renderDocument(
  blocks: readonly SiteBlock[],
  tokens: DesignTokensV1,
  registry: BlockRegistry,
): ReactElement {
  return createElement(
    "main",
    { className: designTokenClassName(tokens) },
    ...blocks.map((block, index) => registry.render(block, String(index))),
  );
}

export function renderDraftPreview(
  document: DraftPreviewDocument,
  registry: BlockRegistry,
): ReactElement {
  if (document.kind !== "draft-preview" || document.versionId.length === 0) {
    throw new TypeError("Preview wymaga jawnej wersji draftu.");
  }
  return renderDocument(document.blocks, document.designTokens, registry);
}

export function renderPublishedPage(
  document: PublishedPageDocument,
  registry: BlockRegistry,
): ReactElement {
  if (
    document.kind !== "publication" ||
    document.publicationId.length === 0 ||
    !/^[a-f0-9]{64}$/.test(document.snapshotHash)
  ) {
    throw new TypeError("Renderer publiczny wymaga zweryfikowanej publikacji.");
  }
  return renderDocument(document.blocks, document.designTokens, registry);
}
