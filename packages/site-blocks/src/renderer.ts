import { createElement, type ReactElement } from "react";

import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import designTokensSchema from "@saas-core/contracts/site-blocks/design-tokens.v1.schema.json";

import {
  pagePresentationClassName,
  siteAppearanceClassName,
  type SiteAppearance,
} from "./appearance";
import {
  renderSiteHeader,
  renderSiteFooter,
  renderResponsiveNavigation,
} from "./site-chrome";
import { InvalidDesignTokensError } from "./errors";
import type {
  BlockRegistry,
  BlockImageRenderer,
  PublishedFormRenderer,
  BlockRenderOptions,
  DesignTokensV1,
  PagePresentationV1,
  DraftPreviewDocument,
  NavigationLink,
  IndexPagination,
  PaginationLabels,
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
export function renderNavigation(
  links: readonly NavigationLink[],
  label: string,
): ReactElement | null {
  if (links.length === 0) return null;
  const children = new Map<string, NavigationLink[]>();
  for (const link of links) {
    if (link.parent_page_id === null) continue;
    const siblings = children.get(link.parent_page_id) ?? [];
    siblings.push(link);
    children.set(link.parent_page_id, siblings);
  }
  return createElement(
    "nav",
    { className: "site-nav", "aria-label": label },
    createElement(
      "ul",
      null,
      ...links
        .filter((link) => link.parent_page_id === null)
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

/** Previous and next only. A numbered strip of a hundred pages is a wall of
 *  links nobody uses, and every one of those pages is already in the sitemap,
 *  which is how a crawler reaches them. */
function renderPagination(
  pagination: IndexPagination | null | undefined,
  labels: PaginationLabels,
): ReactElement | null {
  if (!pagination || pagination.pages <= 1) return null;
  const links: ReactElement[] = [];
  if (pagination.previous_path !== null) {
    links.push(
      createElement(
        "a",
        { key: "previous", rel: "prev", href: pagination.previous_path },
        labels.previous,
      ),
    );
  }
  links.push(
    createElement(
      "span",
      { key: "position" },
      labels.position(pagination.page, pagination.pages),
    ),
  );
  if (pagination.next_path !== null) {
    links.push(
      createElement(
        "a",
        { key: "next", rel: "next", href: pagination.next_path },
        labels.next,
      ),
    );
  }
  return createElement(
    "nav",
    { className: "site-pagination", "aria-label": labels.label },
    ...links,
  );
}

const DEFAULT_PAGINATION_LABELS: PaginationLabels = {
  label: "Strony",
  previous: "Poprzednia",
  next: "Następna",
  position: (page, pages) => `Strona ${page} z ${pages}`,
};

function renderDocument(
  blocks: readonly SiteBlock[],
  tokens: DesignTokensV1,
  registry: BlockRegistry,
  navigation: readonly NavigationLink[] = [],
  navigationLabel = "Menu",
  contentElement: "main" | "div" = "main",
  pagination: IndexPagination | null = null,
  paginationLabels: PaginationLabels = DEFAULT_PAGINATION_LABELS,
  imageRenderer?: BlockImageRenderer,
  appearance?: SiteAppearance | null,
  formRenderer?: PublishedFormRenderer,
  options?: BlockRenderOptions,
  pagePresentation?: PagePresentationV1 | null,
): ReactElement {
  const menu = renderNavigation(navigation, navigationLabel);
  const content = createElement(
    "div",
    {
      className: [
        designTokenClassName(appearance?.designTokens ?? tokens),
        appearance ? siteAppearanceClassName(appearance) : "",
        pagePresentationClassName(pagePresentation),
        contentElement === "div" ? "site-theme--preview" : "",
      ]
        .filter(Boolean)
        .join(" "),
    },
    appearance ? renderSiteHeader(appearance, menu) : menu,
    createElement(
      contentElement,
      null,
      ...blocks.map((block, index) =>
        registry.render(
          block,
          String(index),
          undefined,
          imageRenderer,
          formRenderer ? (data) => formRenderer(data, index) : undefined,
          options,
        ),
      ),
      renderPagination(pagination, paginationLabels),
    ),
    appearance ? renderSiteFooter(appearance) : null,
  );
  return appearance
    ? createElement(
        "div",
        {
          className: `site-frame${contentElement === "div" ? " site-frame--preview" : ""}`,
        },
        content,
        renderResponsiveNavigation(
          appearance,
          navigation,
          navigationLabel,
          menu,
        ),
      )
    : content;
}

export function renderDraftPreview(
  document: DraftPreviewDocument,
  registry: BlockRegistry,
  imageRenderer?: BlockImageRenderer,
): ReactElement {
  if (document.kind !== "draft-preview" || document.versionId.length === 0) {
    throw new TypeError("Preview wymaga jawnej wersji draftu.");
  }
  // A preview is always embedded inside another page — the panel, a template
  // gallery, a dialog — and HTML allows one non-hidden `main` per document.
  // Emitting a landmark here would put several on the operator's screen and
  // leave a screen reader with no way to say which one is the page.
  return renderDocument(
    document.blocks,
    document.designTokens,
    registry,
    [],
    "Menu",
    "div",
    null,
    DEFAULT_PAGINATION_LABELS,
    imageRenderer,
    document.appearance,
    undefined,
    undefined,
    document.pagePresentation,
  );
}

export function renderPublishedPage(
  document: PublishedPageDocument,
  registry: BlockRegistry,
  formRenderer?: PublishedFormRenderer,
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
    "main",
    document.pagination ?? null,
    document.paginationLabels ?? DEFAULT_PAGINATION_LABELS,
    undefined,
    document.appearance,
    formRenderer,
    { preview: false, locale: document.locale ?? "pl" },
    document.pagePresentation,
  );
}
