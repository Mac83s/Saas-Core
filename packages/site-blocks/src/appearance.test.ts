import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  parseSiteAppearance,
  siteAppearanceClassName,
  type SiteAppearance,
} from "./appearance";
import {
  renderSiteHeader,
  renderSiteFooter,
  renderResponsiveNavigation,
} from "./site-chrome";

const appearance: SiteAppearance = {
  schemaVersion: 1,
  designTokens: {
    schemaVersion: 1,
    palette: "blue",
    typography: "sans",
    radius: "medium",
    spacing: "comfortable",
  },
  font: "georgia",
  width: "wide",
  buttons: "pill",
  header: {
    layout: "classic",
    brand: "<script>Clinic</script>",
    tagline: "Care",
  },
  footer: {
    layout: "columns",
    text: "Contact",
    links: [{ label: "About", href: "/about/" }],
  },
  navigation: { mobile: "bottom", tablet: "drawer" },
};
describe("site appearance contract and chrome", () => {
  it("accepts controlled settings and rejects arbitrary CSS, fonts and executable links", () => {
    expect(parseSiteAppearance(appearance)).toEqual(appearance);
    expect(siteAppearanceClassName(appearance)).toContain("site-font--georgia");
    for (const invalid of [
      { ...appearance, font: "url(evil)" },
      { ...appearance, css: "body{}" },
      {
        ...appearance,
        footer: {
          ...appearance.footer,
          links: [{ label: "Bad", href: "javascript:alert(1)" }],
        },
      },
    ])
      expect(() => parseSiteAppearance(invalid)).toThrow();
  });
  it.each(["classic", "centered", "stacked"] as const)(
    "renders fixed %s headers with escaped content",
    (layout) => {
      const html = renderToStaticMarkup(
        renderSiteHeader({
          ...appearance,
          header: { ...appearance.header, layout },
        }),
      );
      expect(html).toContain(`site-header--${layout}`);
      expect(html).not.toContain("<script>");
      expect(html).toContain("&lt;script&gt;");
    },
  );
  it.each(["simple", "centered", "columns"] as const)(
    "renders fixed %s footers",
    (layout) => {
      const html = renderToStaticMarkup(
        renderSiteFooter({
          ...appearance,
          footer: { ...appearance.footer, layout },
        }),
      );
      expect(html).toContain(`site-footer--${layout}`);
      expect(html).toContain('href="/about/"');
    },
  );
  it("keeps the full menu accessible beyond the four primary tabs", () => {
    const links = Array.from({ length: 6 }, (_, i) => ({
      page_id: String(i),
      parent_page_id: null,
      path: `/page-${i}/`,
      title: `Page ${i}`,
    }));
    const html = renderToStaticMarkup(
      renderResponsiveNavigation(
        appearance,
        links,
        "Menu",
        "Full menu including Page 5",
      ),
    );
    expect(html).toContain("site-mobile--bottom site-tablet--drawer");
    expect(html).toContain("<summary>Menu</summary>");
    expect(html).toContain("Full menu including Page 5");
    expect(html.match(/<a /g)).toHaveLength(4);
  });
});
