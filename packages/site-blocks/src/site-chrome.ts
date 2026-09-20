import { createElement as h, type ReactNode } from "react";
import type { SiteAppearance } from "./appearance";
import type { NavigationLink } from "./types";

export function renderSiteHeader(
  appearance: SiteAppearance,
  navigation?: ReactNode,
) {
  if (appearance.header.layout === "none") return navigation ?? null;
  const { layout, brand, tagline } = appearance.header;
  return h(
    "header",
    { className: `site-header site-header--${layout}` },
    h(
      "div",
      { className: "site-header__brand" },
      h("a", { href: "/" }, brand),
      tagline ? h("p", null, tagline) : null,
    ),
    navigation,
  );
}
export function renderSiteFooter(appearance: SiteAppearance) {
  const { layout, text, links } = appearance.footer;
  if (layout === "none") return null;
  return h(
    "footer",
    { className: `site-footer site-footer--${layout}` },
    text ? h("p", null, text) : null,
    links.length
      ? h(
          "ul",
          null,
          ...links.map((link, i) =>
            h(
              "li",
              { key: i },
              h(
                "a",
                {
                  href: link.href,
                  rel: link.href.startsWith("https://")
                    ? "noreferrer"
                    : undefined,
                },
                link.label,
              ),
            ),
          ),
        )
      : null,
  );
}
/** Every link remains reachable, including children and overflow beyond four tabs. */
export function renderResponsiveNavigation(
  appearance: SiteAppearance,
  links: readonly NavigationLink[],
  label: string,
  navigation: ReactNode,
) {
  if (!links.length) return null;
  const primary = links
    .filter((link) => link.parent_page_id === null)
    .slice(0, 4);
  return h(
    "div",
    {
      className: `site-responsive-nav site-mobile--${appearance.navigation.mobile} site-tablet--${appearance.navigation.tablet}`,
    },
    h(
      "div",
      { className: "site-bottom-links" },
      ...primary.map((link) =>
        h("a", { key: link.page_id, href: link.path }, link.title),
      ),
    ),
    h(
      "details",
      { className: "site-menu-disclosure" },
      h("summary", null, label),
      navigation,
    ),
  );
}
