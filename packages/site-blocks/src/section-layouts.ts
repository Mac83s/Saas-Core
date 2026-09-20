import { createElement as h, type ReactElement } from "react";

import { plainBlockText } from "./block-text";

import type {
  BlockEditor,
  BlockImageRenderer,
  FaqV1Data,
  FeatureListV1Data,
  HeroV3Data,
  JsonObject,
} from "./types";

/** Layout names are validated against the canonical schema before rendering. */
export function renderSectionLayout(
  type: string,
  data: JsonObject,
  editor?: BlockEditor,
  imageRenderer?: BlockImageRenderer,
): ReactElement | null {
  const text = editor?.text ?? plainBlockText;
  const layout = data.layout;
  if (
    typeof layout !== "string" ||
    (layout === "classic" && !(type === "core.feature_list" && data.image))
  )
    return null;
  const props = {
    className: `site-block site-section site-section--${type.replace("core.", "")} site-section--${layout}`,
    "data-block-type": type,
    "data-section-layout": layout,
  };
  if (type === "core.hero") {
    const hero = data as HeroV3Data;
    const title = h(
      "h1",
      editor ? { role: "presentation" } : null,
      text(["title"], hero.title),
    );
    const body = h(
      "div",
      { className: "site-section__body" },
      hero.text ? h("p", null, text(["text"], hero.text)) : null,
      hero.action
        ? h(
            editor ? "span" : "a",
            {
              href: editor ? undefined : hero.action.href,
              rel: hero.action.href.startsWith("https://")
                ? "noreferrer"
                : undefined,
              className: "site-section__action",
            },
            text(["action", "label"], hero.action.label),
          )
        : null,
    );
    const image = hero.image
      ? imageRenderer
        ? imageRenderer(hero.image)
        : h("img", {
            src: `/media/${hero.image.asset_id}`,
            alt: hero.image.alt,
            loading: "eager",
            decoding: "async",
          })
      : null;
    const grouped =
      (layout === "split" && image) ||
      !["classic", "centered", "split"].includes(layout);
    return h(
      "section",
      props,
      grouped
        ? h("div", { className: "site-section__intro" }, title, body)
        : title,
      grouped ? image : body,
      grouped || layout === "split" ? null : image,
    );
  }
  if (type === "core.faq") {
    const faq = data as FaqV1Data;
    return h(
      "section",
      props,
      faq.title
        ? h(
            "h2",
            editor ? { role: "presentation" } : null,
            text(["title"], faq.title),
          )
        : null,
      ["accordion", "stacked", "panels"].includes(layout)
        ? h(
            "div",
            null,
            faq.items.map((item, i) =>
              h(
                "details",
                { key: i, open: editor ? true : undefined },
                h(
                  "summary",
                  null,
                  text(["items", String(i), "question"], item.question),
                ),
                h("p", null, text(["items", String(i), "answer"], item.answer)),
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
                h(
                  "dt",
                  null,
                  text(["items", String(i), "question"], item.question),
                ),
                h(
                  "dd",
                  null,
                  text(["items", String(i), "answer"], item.answer),
                ),
              ),
            ),
          ),
    );
  }
  if (type === "core.feature_list") {
    const offer = data as FeatureListV1Data;
    const photo = offer.image
      ? h(
          "div",
          { className: "site-section__photo" },
          imageRenderer
            ? imageRenderer(offer.image)
            : h("img", {
                src: `/media/${offer.image.asset_id}`,
                alt: offer.image.alt,
                loading: "lazy",
                decoding: "async",
              }),
        )
      : null;
    const heading = offer.title
      ? h(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], offer.title),
        )
      : null;
    if (layout === "specification" || layout === "coverage") {
      return h(
        "section",
        props,
        heading,
        photo,
        h(
          "dl",
          null,
          offer.items.map((item, i) =>
            h(
              "div",
              { key: i },
              h("dt", null, text(["items", String(i), "title"], item.title)),
              item.text
                ? h("dd", null, text(["items", String(i), "text"], item.text))
                : null,
            ),
          ),
        ),
      );
    }
    const ordered = [
      "care_path",
      "field_steps",
      "service_flow",
      "numbered",
      "timeline",
    ].includes(layout);
    return h(
      "section",
      props,
      heading,
      photo,
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
              h(
                "h3",
                editor ? { role: "presentation" } : null,
                text(["items", String(i), "title"], item.title),
              ),
              item.text
                ? h("p", null, text(["items", String(i), "text"], item.text))
                : null,
            ),
          ),
        ),
      ),
    );
  }
  return null;
}
