import { createElement as h, type ReactNode } from "react";

import { plainBlockText } from "./block-text";
import { unfilledPlaceholders } from "./rich-text";

import type {
  BlockComponentProps,
  BlockImageRenderer,
  ProductV1Data,
  QuoteV1Data,
} from "./types";

function externalRel(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

export function picture(
  image: { asset_id: string; alt: string },
  imageRenderer?: BlockImageRenderer,
): ReactNode {
  return imageRenderer
    ? imageRenderer(image)
    : h("img", {
        src: `/media/${image.asset_id}`,
        alt: image.alt,
        loading: "lazy",
        decoding: "async",
      });
}

/** Up to two initials; derived text, so it never goes through the editor.
 *  A template's `[Uzupełnij: …]` is not a name, and a name without letters
 *  has no initials: both give `fallback`. */
export function monogram(author: string | undefined, fallback = "“"): string {
  if (unfilledPlaceholders([{ data: { author: author ?? "" } }]).length > 0)
    return fallback;
  const initials = (author ?? "")
    .split(/\s+/)
    .flatMap((word) => word.match(/\p{L}/u) ?? [])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return initials || fallback;
}

/** An editorial quote, not a review: no rating, and the source is a citation. */
export function QuoteBlock({
  data,
  editor,
  imageRenderer,
  options,
}: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const quote = data as QuoteV1Data;
  const source = quote.source;
  const caption =
    quote.author !== undefined || quote.role !== undefined || source
      ? h(
          "figcaption",
          null,
          quote.author === undefined
            ? null
            : h(
                "span",
                { className: "site-quote__author" },
                text(["author"], quote.author),
              ),
          quote.role === undefined
            ? null
            : h(
                "span",
                { className: "site-quote__role" },
                text(["role"], quote.role),
              ),
          source
            ? h(
                "cite",
                null,
                source.href !== undefined && options?.preview === false
                  ? h(
                      "a",
                      { href: source.href, rel: externalRel(source.href) },
                      text(["source", "label"], source.label),
                    )
                  : text(["source", "label"], source.label),
              )
            : null,
        )
      : null;
  return h(
    "section",
    {
      className: `site-block site-section site-section--quote site-section--${quote.layout ?? "typographic"}`,
      "data-block-type": "core.quote",
      "data-section-layout": quote.layout,
    },
    quote.layout === "portrait"
      ? h(
          "div",
          { className: "site-quote__portrait" },
          quote.image
            ? picture(quote.image, imageRenderer)
            : h(
                "span",
                { className: "site-quote__monogram", "aria-hidden": true },
                monogram(quote.author),
              ),
        )
      : null,
    h(
      "figure",
      { className: "site-quote site-quote--large" },
      h("blockquote", null, h("p", null, text(["quote"], quote.quote))),
      caption,
    ),
    quote.context === undefined
      ? null
      : h(
          "p",
          { className: "site-quote__context" },
          text(["context"], quote.context),
        ),
  );
}

/** A product presentation. Deliberately no price, stock or cart. */
export function ProductBlock({
  data,
  editor,
  imageRenderer,
}: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const product = data as ProductV1Data;
  const layout = product.layout ?? "showcase";
  const [first, ...rest] = product.images ?? [];
  const caption = (value: string | undefined, index: number) =>
    value === undefined
      ? null
      : h(
          "figcaption",
          null,
          text(["images", String(index), "caption"], value),
        );
  return h(
    "section",
    {
      className: `site-block site-section site-section--product site-section--${layout}`,
      "data-block-type": "core.product",
      "data-section-layout": layout,
    },
    h(
      "div",
      { className: "site-section__intro" },
      h(
        "h2",
        editor ? { role: "presentation" } : null,
        text(["title"], product.title),
      ),
      product.tagline === undefined
        ? null
        : h(
            "p",
            { className: "site-section__lead" },
            text(["tagline"], product.tagline),
          ),
    ),
    first
      ? h(
          "div",
          { className: "site-product__gallery" },
          h(
            "figure",
            { className: "site-product__photo" },
            picture(first, imageRenderer),
            caption(first.caption, 0),
          ),
          rest.length > 0
            ? h(
                "ul",
                { className: "site-product__strip" },
                rest.map((image, index) =>
                  h(
                    "li",
                    { key: index },
                    h(
                      "figure",
                      null,
                      picture(image, imageRenderer),
                      caption(image.caption, index + 1),
                    ),
                  ),
                ),
              )
            : null,
        )
      : null,
    h(
      "div",
      { className: "site-product__details" },
      product.text === undefined
        ? null
        : h(
            "div",
            { className: "site-product__text" },
            // The editor edits the whole description as one field; a
            // publication splits it into paragraphs on blank lines.
            editor
              ? h("p", null, text(["text"], product.text))
              : product.text
                  .split(/\n\s*\n/)
                  .map((paragraph) => paragraph.trim())
                  .filter(Boolean)
                  .map((paragraph, index) => h("p", { key: index }, paragraph)),
          ),
      product.specs
        ? h(
            "dl",
            { className: "site-product__specs" },
            product.specs.map((spec, index) =>
              h(
                "div",
                { key: index },
                h(
                  "dt",
                  null,
                  text(["specs", String(index), "label"], spec.label),
                ),
                h(
                  "dd",
                  null,
                  text(["specs", String(index), "value"], spec.value),
                ),
              ),
            ),
          )
        : null,
      product.uses
        ? h(
            "ul",
            { className: "site-product__uses" },
            product.uses.map((use, index) =>
              h(
                "li",
                { key: index },
                h(
                  "h3",
                  editor ? { role: "presentation" } : null,
                  text(["uses", String(index), "title"], use.title),
                ),
                use.text === undefined
                  ? null
                  : h(
                      "p",
                      null,
                      text(["uses", String(index), "text"], use.text),
                    ),
              ),
            ),
          )
        : null,
      product.action
        ? h(
            editor ? "span" : "a",
            {
              className: "site-section__action",
              href: editor ? undefined : product.action.href,
              rel: editor ? undefined : externalRel(product.action.href),
            },
            text(["action", "label"], product.action.label),
          )
        : null,
    ),
  );
}
