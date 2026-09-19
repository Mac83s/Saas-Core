import { createElement as h, type ReactElement } from "react";

import type {
  FaqV1Data,
  FeatureListV1Data,
  HeroV3Data,
  JsonObject,
} from "./types";

/** Layout names are validated against the canonical schema before rendering. */
export function renderSectionLayout(
  type: string,
  data: JsonObject,
): ReactElement | null {
  const layout = data.layout;
  if (typeof layout !== "string" || layout === "classic") return null;
  const props = {
    className: `site-block site-section site-section--${type.replace("core.", "")} site-section--${layout}`,
    "data-block-type": type,
    "data-section-layout": layout,
  };
  if (type === "core.hero") {
    const hero = data as HeroV3Data;
    const title = h("h1", null, hero.title);
    const body = h(
      "div",
      { className: "site-section__body" },
      hero.text ? h("p", null, hero.text) : null,
      hero.action
        ? h(
            "a",
            {
              href: hero.action.href,
              rel: hero.action.href.startsWith("https://")
                ? "noreferrer"
                : undefined,
              className: "site-section__action",
            },
            hero.action.label,
          )
        : null,
    );
    const image = hero.image
      ? h("img", {
          src: `/media/${hero.image.asset_id}`,
          alt: hero.image.alt,
          loading: "eager",
          decoding: "async",
        })
      : null;
    return h(
      "section",
      props,
      layout === "split" && image
        ? h("div", { className: "site-section__intro" }, title, body)
        : title,
      layout === "split" && image ? image : body,
      layout === "split" ? null : image,
    );
  }
  if (type === "core.faq") {
    const faq = data as FaqV1Data;
    return h(
      "section",
      props,
      faq.title ? h("h2", null, faq.title) : null,
      layout === "accordion"
        ? h(
            "div",
            null,
            faq.items.map((item, i) =>
              h(
                "details",
                { key: i },
                h("summary", null, item.question),
                h("p", null, item.answer),
              ),
            ),
          )
        : h(
            "dl",
            null,
            faq.items.map((item, i) =>
              h(
                "div",
                { key: i },
                h("dt", null, item.question),
                h("dd", null, item.answer),
              ),
            ),
          ),
    );
  }
  if (type === "core.feature_list") {
    const offer = data as FeatureListV1Data;
    const heading = offer.title ? h("h2", null, offer.title) : null;
    if (layout === "specification" || layout === "coverage") {
      return h(
        "section",
        props,
        heading,
        h(
          "dl",
          null,
          offer.items.map((item, i) =>
            h(
              "div",
              { key: i },
              h("dt", null, item.title),
              item.text ? h("dd", null, item.text) : null,
            ),
          ),
        ),
      );
    }
    const ordered = ["care_path", "field_steps", "service_flow"].includes(
      layout,
    );
    return h(
      "section",
      props,
      heading,
      h(
        ordered ? "ol" : "ul",
        null,
        offer.items.map((item, i) =>
          h(
            "li",
            { key: i },
            ordered
              ? h(
                  "span",
                  { className: "site-section__step", "aria-hidden": true },
                  String(i + 1).padStart(2, "0"),
                )
              : null,
            h(
              "div",
              null,
              h("h3", null, item.title),
              item.text ? h("p", null, item.text) : null,
            ),
          ),
        ),
      ),
    );
  }
  return null;
}
