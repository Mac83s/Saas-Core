import { createElement, type ReactElement } from "react";

import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import designTokensSchema from "@saas-core/contracts/site-blocks/design-tokens.v1.schema.json";

import { InvalidDesignTokensError } from "./errors";
import type {
  BlockRegistry,
  DesignTokensV1,
  DraftPreviewDocument,
  NavigationLink,
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

/** Nested one level deep, which is as far as the editor lets a menu go. The
 *  links are plain paths from the publication snapshot — never data-supplied
 *  URLs — so the renderer's no-arbitrary-HTML rule still holds. */
function renderNavigation(
  links: readonly NavigationLink[],
  label: string,
): ReactElement | null {
  if (links.length === 0) return null;
  const children = new Map<string, NavigationLink[]>();
  for (const link of links) {
    if (link.parent_id === null) continue;
    const siblings = children.get(link.parent_id) ?? [];
    siblings.push(link);
    children.set(link.parent_id, siblings);
  }
  return createElement(
    "nav",
    { className: "site-nav", "aria-label": label },
    createElement(
      "ul",
      null,
      ...links
        .filter((link) => link.parent_id === null)
        .map((link) =>
          createElement(
            "li",
            { key: link.page_id },
            createElement("a", { href: link.path }, link.title),
            children.has(link.page_id)
              ? createElement(
                  "ul",
                  null,
                  ...(children.get(link.page_id) ?? []).map((child) =>
                    createElement(
                      "li",
                      { key: child.page_id },
                      createElement("a", { href: child.path }, child.title),
                    ),
                  ),
                )
              : null,
          ),
        ),
    ),
  );
}

function renderDocument(
  blocks: readonly SiteBlock[],
  tokens: DesignTokensV1,
  registry: BlockRegistry,
  navigation: readonly NavigationLink[] = [],
  navigationLabel = "Menu",
): ReactElement {
  return createElement(
    "div",
    { className: designTokenClassName(tokens) },
    renderNavigation(navigation, navigationLabel),
    createElement(
      "main",
      null,
      ...blocks.map((block, index) => registry.render(block, String(index))),
    ),
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
  return renderDocument(
    document.blocks,
    document.designTokens,
    registry,
    document.navigation ?? [],
    document.navigationLabel ?? "Menu",
  );
}
