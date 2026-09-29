import { createElement as h, type ReactNode } from "react";

import { renderImage } from "./ai-badge";
import { plainBlockText } from "./block-text";
import { publicImage } from "./public-image";
import type { BlockComponentProps, GalleryV1Data } from "./types";

type Layout = NonNullable<GalleryV1Data["layout"]>;

/** How wide each layout draws a photo — what the browser needs to pick a copy. */
const SIZES: Record<Layout, string> = {
  photo_story: "(min-width: 64rem) 60vw, 100vw",
  captioned_grid: "(min-width: 64rem) 33vw, (min-width: 48rem) 50vw, 100vw",
  dominant_details: "(min-width: 64rem) 25vw, (min-width: 48rem) 50vw, 100vw",
  interleaved: "(min-width: 48rem) 50vw, 100vw",
  project_mosaic: "(min-width: 64rem) 33vw, (min-width: 48rem) 50vw, 100vw",
  photo_steps: "(min-width: 64rem) 33vw, (min-width: 48rem) 50vw, 100vw",
};

function external(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

/**
 * Photos with titles and captions (F4-P3). Plain markup — no script, no
 * carousel: every photo is in the page and on a phone they simply stack. A
 * photo is optional, so a gallery can be laid out before the pictures exist;
 * an item's link is quiet, the section's one primary action is `action`.
 */
export function GalleryBlock({
  data,
  editor,
  imageRenderer,
}: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const gallery = data as GalleryV1Data;
  const layout: Layout = gallery.layout ?? "captioned_grid";
  const intro =
    gallery.title !== undefined || gallery.lead !== undefined
      ? h(
          "div",
          { className: "site-section__intro" },
          gallery.title === undefined
            ? null
            : h(
                "h2",
                editor ? { role: "presentation" } : null,
                text(["title"], gallery.title),
              ),
          gallery.lead === undefined
            ? null
            : h(
                "p",
                { className: "site-section__lead" },
                text(["lead"], gallery.lead),
              ),
        )
      : null;
  const item = (entry: GalleryV1Data["items"][number], index: number) => {
    const path = (...rest: string[]) => ["items", String(index), ...rest];
    const photo: ReactNode = entry.image
      ? h(
          "div",
          { className: "site-gallery__photo" },
          renderImage(
            entry.image,
            publicImage(entry.image, {
              // The dominant photo takes most of the section.
              sizes:
                layout === "dominant_details" && index === 0
                  ? "(min-width: 48rem) 60vw, 100vw"
                  : SIZES[layout],
            }),
            imageRenderer,
          ),
        )
      : null;
    const caption =
      entry.title !== undefined ||
      entry.caption !== undefined ||
      entry.link !== undefined
        ? h(
            "figcaption",
            { className: "site-gallery__text" },
            entry.title === undefined
              ? null
              : h(
                  "h3",
                  editor ? { role: "presentation" } : null,
                  text(path("title"), entry.title),
                ),
            entry.caption === undefined
              ? null
              : h("p", null, text(path("caption"), entry.caption)),
            entry.link === undefined
              ? null
              : h(
                  editor ? "span" : "a",
                  {
                    className: "site-gallery__link",
                    href: editor ? undefined : entry.link.href,
                    rel: editor ? undefined : external(entry.link.href),
                  },
                  text(path("link", "label"), entry.link.label),
                ),
          )
        : null;
    return h(
      "li",
      {
        key: index,
        className: `site-gallery__item${entry.image ? "" : " site-gallery__item--text"}`,
      },
      h("figure", null, photo, caption),
    );
  };
  return h(
    "section",
    {
      className: `site-block site-section site-section--gallery site-section--${layout}`,
      "data-block-type": "core.gallery",
      "data-section-layout": layout,
    },
    intro,
    h(
      // Steps have an order a screen reader should announce.
      layout === "photo_steps" ? "ol" : "ul",
      { className: "site-gallery__items" },
      gallery.items.map(item),
    ),
    gallery.action
      ? h(
          editor ? "span" : "a",
          {
            className: "site-section__action",
            href: editor ? undefined : gallery.action.href,
            rel: editor ? undefined : external(gallery.action.href),
          },
          text(["action", "label"], gallery.action.label),
        )
      : null,
  );
}
