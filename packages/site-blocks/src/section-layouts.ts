import { createElement as h, type ReactElement } from "react";

import { plainBlockText } from "./block-text";
import { renderImage } from "./ai-badge";
import { FULL_WIDTH, HALF_WIDTH, publicImage } from "./public-image";
import { withSecondaryAction } from "./editorial-blocks";
import {
  FEATURE_LIST_V5_LAYOUTS,
  featureListAction,
  featureListV5Body,
} from "./feature-list-layouts";

import type {
  BlockEditor,
  BlockImageRenderer,
  BlockTextRenderer,
  FaqV1Data,
  FeatureListV4Data,
  FeatureListV5Data,
  HeroV6Data,
  JsonObject,
} from "./types";

/** feature_list v4 intro: the heading alone keeps its legacy markup; with a
 *  lead both move into one intro, which takes the heading's grid cell. */
export function featureListIntro(
  data: FeatureListV4Data,
  text: BlockTextRenderer,
  editor?: BlockEditor,
  withLead = true,
): ReactElement | null {
  const heading = data.title
    ? h(
        "h2",
        editor ? { role: "presentation" } : null,
        text(["title"], data.title),
      )
    : null;
  if (!withLead || !data.lead) return heading;
  return h(
    "div",
    { className: "site-section__intro" },
    heading,
    h("p", { className: "site-section__lead" }, text(["lead"], data.lead)),
  );
}

/** feature_list v4 notes panel. Every layout renders it; none hides it. */
export function featureListNote(
  data: FeatureListV4Data,
  text: BlockTextRenderer,
  editor?: BlockEditor,
): ReactElement | null {
  if (!data.note) return null;
  return h(
    "aside",
    { className: "site-section__note" },
    data.note.title
      ? h(
          "h3",
          editor ? { role: "presentation" } : null,
          text(["note", "title"], data.note.title),
        )
      : null,
    h("p", null, text(["note", "text"], data.note.text)),
  );
}

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
    (layout === "classic" &&
      !(
        type === "core.feature_list" &&
        (data.image || data.lead || data.note || data.action)
      ))
  )
    return null;
  const props = {
    className: `site-block site-section site-section--${type.replace("core.", "")} site-section--${layout}`,
    "data-block-type": type,
    "data-section-layout": layout,
  };
  if (type === "core.hero") {
    const hero = data as HeroV6Data;
    const title = h(
      "h1",
      editor ? { role: "presentation" } : null,
      text(["title"], hero.title),
    );
    const body = h(
      "div",
      { className: "site-section__body" },
      hero.text ? h("p", null, text(["text"], hero.text)) : null,
      withSecondaryAction(
        hero.action
          ? h(
              editor ? "span" : "a",
              {
                href: editor ? undefined : hero.action.href,
                rel:
                  !editor && hero.action.href.startsWith("https://")
                    ? "noreferrer"
                    : undefined,
                className: "site-section__action",
              },
              text(["action", "label"], hero.action.label),
            )
          : null,
        hero.secondaryAction,
        text,
        editor,
      ),
    );
    const image = hero.image
      ? renderImage(
          hero.image,
          publicImage(hero.image, {
            sizes: layout === "split" ? HALF_WIDTH : FULL_WIDTH,
            loading: "eager",
          }),
          imageRenderer,
        )
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
    const offer = data as FeatureListV5Data;
    // Built per layout: the editor adapter records every text it renders.
    const note = featureListNote(offer, text, editor);
    const action = featureListAction(offer, text, editor);
    const v5 = FEATURE_LIST_V5_LAYOUTS.find((name) => name === layout);
    if (v5)
      return h(
        "section",
        props,
        featureListIntro(offer, text, editor),
        ...featureListV5Body(v5, offer, text, editor, note, action),
      );
    // After the v5 layouts, which draw no photo: an image renderer records
    // what it is handed.
    const photo = offer.image
      ? h(
          "div",
          { className: "site-section__photo" },
          renderImage(offer.image, publicImage(offer.image), imageRenderer),
        )
      : null;
    if (layout === "specification" || layout === "coverage") {
      return h(
        "section",
        props,
        featureListIntro(offer, text, editor),
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
        note,
        action,
      );
    }
    const ordered = [
      "care_path",
      "field_steps",
      "service_flow",
      "numbered",
      "timeline",
      "steps_notes",
    ].includes(layout);
    const list = h(
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
    );
    if (layout === "benefits_commentary") {
      // The lead leaves the intro and joins the note: one prominent
      // commentary beside the benefits, read after them.
      const heading = featureListIntro(offer, text, editor, false);
      return h(
        "section",
        props,
        heading,
        photo,
        list,
        offer.lead || note
          ? h(
              "div",
              { className: "site-section__commentary" },
              offer.lead
                ? h(
                    "p",
                    { className: "site-section__lead" },
                    text(["lead"], offer.lead),
                  )
                : null,
              note,
            )
          : null,
        action,
      );
    }
    return h(
      "section",
      props,
      featureListIntro(offer, text, editor),
      photo,
      list,
      note,
      action,
    );
  }
  return null;
}
