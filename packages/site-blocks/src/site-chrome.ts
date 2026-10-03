import { createElement as h, type ReactNode } from "react";
import type { SiteAppearance } from "./appearance";
import type {
  AppearanceLang,
  ArticleByline,
  LanguageLink,
  NavigationLink,
} from "./types";

/** Plain links, so the switch works without JavaScript: each language at the
 *  page's own version there, or at its home (TL14). The current one is
 *  marked rather than linked again. */
export function renderLanguageSwitcher(
  links: readonly LanguageLink[] | undefined,
  label: string,
) {
  if (!links || links.length < 2) return null;
  return h(
    "nav",
    { className: "site-language-switch", "aria-label": label },
    h(
      "ul",
      null,
      ...links.map((link) =>
        h(
          "li",
          { key: link.locale },
          h(
            "a",
            {
              href: link.path,
              hrefLang: link.locale,
              lang: link.locale,
              "aria-current": link.current ? "true" : undefined,
            },
            link.name,
          ),
        ),
      ),
    ),
  );
}

/** An article's author and day, in the page's language and the company's
 *  zone. The day the text changed is added once it is a later one. */
export function renderArticleByline(
  article: ArticleByline | null | undefined,
  locale: string,
  updatedLabel: string,
) {
  if (!article) return null;
  const day = (moment: string | null | undefined) => {
    const date = moment ? new Date(moment) : null;
    if (!date || Number.isNaN(date.getTime())) return null;
    const format = (timeZone: string) =>
      new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone }).format(
        date,
      );
    try {
      return { moment: date, text: format(article.timeZone || "UTC") };
    } catch {
      // A zone this runtime does not know.
      return { moment: date, text: format("UTC") };
    }
  };
  const published = day(article.publishedAt);
  const changed = day(article.updatedAt);
  const updated =
    changed &&
    (!published ||
      (changed.moment > published.moment && changed.text !== published.text))
      ? changed
      : null;
  if (!article.authorName && !published && !updated) return null;
  return h(
    "p",
    { className: "site-article-byline" },
    article.authorName ? h("span", null, article.authorName) : null,
    published
      ? h("time", { dateTime: published.moment.toISOString() }, published.text)
      : null,
    updated
      ? h(
          "span",
          null,
          `${updatedLabel} `,
          h("time", { dateTime: updated.moment.toISOString() }, updated.text),
        )
      : null,
  );
}

export function renderSiteHeader(
  appearance: SiteAppearance,
  navigation?: ReactNode,
  lang?: AppearanceLang,
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
      tagline ? h("p", { lang: lang?.["header.tagline"] }, tagline) : null,
    ),
    navigation,
  );
}
/** `lang` names the texts still in the site's language on a page in another
 *  one, so a screen reader and a search engine read them as that language. */
export function renderSiteFooter(
  appearance: SiteAppearance,
  lang?: AppearanceLang,
) {
  const { layout, text, links } = appearance.footer;
  if (layout === "none") return null;
  return h(
    "footer",
    { className: `site-footer site-footer--${layout}` },
    text ? h("p", { lang: lang?.["footer.text"] }, text) : null,
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
                  lang: lang?.[`footer.links.${i}.label`],
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
        h(
          "a",
          { key: link.page_id, href: link.path, lang: link.lang },
          link.title,
        ),
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
