import { createElement as h, type ReactNode } from "react";

import { renderImage } from "./ai-badge";
import { plainBlockText } from "./block-text";
import { ProductBlock, withSecondaryAction } from "./editorial-blocks";
import { HALF_WIDTH, publicImage } from "./public-image";
import type { BlockComponentProps, ProductV3Data } from "./types";

type Layout = NonNullable<ProductV3Data["layout"]>;
type Path = (string | number)[];

function externalRel(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

/**
 * `core.product` in any layout (F4-P4). The showcase is still drawn by
 * `ProductBlock`, byte for byte what v1 and v2 rendered; the seven further
 * layouts each read their own list — details, grouped parameters with
 * documents, uses, what is included, variants, materials, ordering steps. No
 * price, stock or cart in any of them, and every class stays in the product's
 * own namespace (`site-product__…`).
 */
export function ProductV3Block(props: BlockComponentProps) {
  const product = props.data as ProductV3Data;
  const layout: Layout = product.layout ?? "showcase";
  if (layout === "showcase") return ProductBlock(props);
  const { editor, imageRenderer } = props;
  const text = editor?.text ?? plainBlockText;
  const edit = (path: Path, value: string) => text(path.map(String), value);
  const heading = (path: Path, value: string) =>
    h("h3", editor ? { role: "presentation" } : null, edit(path, value));
  const paragraph = (path: Path, value?: string, className?: string) =>
    value === undefined
      ? null
      : h("p", className ? { className } : null, edit(path, value));
  const photo = (image: { asset_id: string; alt: string }, sizes: string) =>
    renderImage(image, publicImage(image, { sizes }), imageRenderer);
  const [first] = product.images ?? [];
  const leadPhoto = (sizes: string) =>
    first
      ? h(
          "figure",
          { className: "site-product__photo" },
          photo(first, sizes),
          first.caption === undefined
            ? null
            : h(
                "figcaption",
                null,
                edit(["images", 0, "caption"], first.caption),
              ),
        )
      : null;

  let body: ReactNode = null;
  if (layout === "detail")
    body = h(
      "div",
      { className: "site-product__detail" },
      leadPhoto("(min-width: 48rem) 60vw, 100vw"),
      product.details
        ? h(
            "ol",
            { className: "site-product__notes" },
            product.details.map((detail, index) =>
              h(
                "li",
                { key: index },
                heading(["details", index, "title"], detail.title),
                paragraph(["details", index, "text"], detail.text),
              ),
            ),
          )
        : null,
    );
  if (layout === "spec_groups") {
    // A parameter with a `group` opens a group; the ones after it follow.
    const groups: { title?: string; at: number; rows: number[] }[] = [];
    (product.specs ?? []).forEach((spec, index) => {
      if (spec.group !== undefined || groups.length === 0)
        groups.push({ title: spec.group, at: index, rows: [] });
      groups.at(-1)!.rows.push(index);
    });
    body = [
      h(
        "div",
        { key: "specs", className: "site-product__spec-groups" },
        groups.map((group) =>
          h(
            "div",
            { key: group.at, className: "site-product__spec-group" },
            group.title === undefined
              ? null
              : heading(["specs", group.at, "group"], group.title),
            h(
              "dl",
              { className: "site-product__specs" },
              group.rows.map((index) => {
                const spec = product.specs![index]!;
                return h(
                  "div",
                  { key: index },
                  h("dt", null, edit(["specs", index, "label"], spec.label)),
                  h("dd", null, edit(["specs", index, "value"], spec.value)),
                );
              }),
            ),
          ),
        ),
      ),
      product.documents
        ? h(
            "ul",
            { key: "documents", className: "site-product__documents" },
            product.documents.map((document, index) =>
              h(
                "li",
                { key: index },
                h(
                  editor ? "span" : "a",
                  {
                    className: "site-product__document",
                    href: editor ? undefined : document.href,
                    rel: editor ? undefined : externalRel(document.href),
                  },
                  edit(["documents", index, "label"], document.label),
                ),
                paragraph(["documents", index, "note"], document.note),
              ),
            ),
          )
        : null,
    ];
  }
  if (layout === "uses")
    body = product.uses
      ? h(
          "ul",
          { className: "site-product__use-cards" },
          product.uses.map((use, index) =>
            h(
              "li",
              { key: index },
              use.image
                ? h(
                    "div",
                    { className: "site-product__use-photo" },
                    photo(
                      use.image,
                      "(min-width: 64rem) 33vw, (min-width: 48rem) 50vw, 100vw",
                    ),
                  )
                : null,
              heading(["uses", index, "title"], use.title),
              paragraph(["uses", index, "text"], use.text),
            ),
          ),
        )
      : null;
  if (layout === "in_the_box")
    body = h(
      "div",
      { className: "site-product__box" },
      leadPhoto(HALF_WIDTH),
      product.included
        ? h(
            "ul",
            { className: "site-product__included" },
            product.included.map((item, index) =>
              h(
                "li",
                { key: index },
                item.quantity === undefined
                  ? null
                  : h(
                      "span",
                      { className: "site-product__quantity" },
                      edit(["included", index, "quantity"], item.quantity),
                    ),
                h(
                  "div",
                  null,
                  heading(["included", index, "title"], item.title),
                  paragraph(["included", index, "text"], item.text),
                ),
              ),
            ),
          )
        : null,
    );
  if (layout === "variant_guide")
    body = product.variants
      ? h(
          "ul",
          { className: "site-product__variants" },
          product.variants.map((variant, index) =>
            h(
              "li",
              { key: index },
              heading(["variants", index, "title"], variant.title),
              paragraph(
                ["variants", index, "fit"],
                variant.fit,
                "site-product__fit",
              ),
              paragraph(["variants", index, "text"], variant.text),
            ),
          ),
        )
      : null;
  if (layout === "materials")
    body = product.materials
      ? h(
          "ul",
          { className: "site-product__materials" },
          product.materials.map((material, index) =>
            h(
              "li",
              {
                key: index,
                className: material.image
                  ? undefined
                  : "site-product__material--plain",
              },
              material.image
                ? h(
                    "div",
                    { className: "site-product__swatch" },
                    photo(material.image, "(min-width: 48rem) 25vw, 50vw"),
                  )
                : null,
              heading(["materials", index, "title"], material.title),
              paragraph(["materials", index, "text"], material.text),
            ),
          ),
        )
      : null;
  if (layout === "how_to_order")
    body = product.steps
      ? h(
          "ol",
          { className: "site-product__steps" },
          product.steps.map((step, index) =>
            h(
              "li",
              { key: index },
              heading(["steps", index, "title"], step.title),
              paragraph(["steps", index, "text"], step.text),
            ),
          ),
        )
      : null;

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
        edit(["title"], product.title),
      ),
      paragraph(["tagline"], product.tagline, "site-section__lead"),
    ),
    product.text === undefined
      ? null
      : h(
          "div",
          { className: "site-product__text" },
          // As in the showcase: one field in the editor, paragraphs on the page.
          editor
            ? h("p", null, edit(["text"], product.text))
            : product.text
                .split(/\n\s*\n/)
                .map((part) => part.trim())
                .filter(Boolean)
                .map((part, index) => h("p", { key: index }, part)),
        ),
    body,
    withSecondaryAction(
      product.action
        ? h(
            editor ? "span" : "a",
            {
              className: "site-section__action",
              href: editor ? undefined : product.action.href,
              rel: editor ? undefined : externalRel(product.action.href),
            },
            edit(["action", "label"], product.action.label),
          )
        : null,
      product.secondaryAction,
      text,
      editor,
    ),
  );
}
