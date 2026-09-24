import {
  cloneElement,
  createElement as h,
  type ReactElement,
  type ReactNode,
} from "react";

import type { BlockImageRenderer } from "./types";

type Locale = "pl" | "en";

const ALT_SUFFIX: Record<Locale, string> = {
  pl: " — obraz wygenerowany przez AI",
  en: " — AI-generated image",
};

/** A block's own `<img>`, handed to the page's renderer when it has one. */
export function renderImage(
  image: { asset_id: string; alt: string },
  element: ReactElement<{ alt?: string }>,
  imageRenderer?: BlockImageRenderer,
): ReactNode {
  return imageRenderer ? imageRenderer(image, element) : element;
}

/** The visible AI marking (ADR-059 pkt 7): an "AI" badge over the image and
 *  the same words for a screen reader in its `alt`. The badge itself is
 *  hidden from assistive technology, so nothing is read twice. */
export function withAiBadge(
  element: ReactElement<{ alt?: string }>,
  locale: Locale = "pl",
): ReactElement {
  return h(
    "span",
    { className: "site-ai-media" },
    cloneElement(element, {
      alt: `${element.props.alt ?? ""}${ALT_SUFFIX[locale]}`,
    }),
    h("span", { className: "site-ai-badge", "aria-hidden": "true" }, "AI"),
  );
}

/** Badges the listed assets; every other image comes back untouched. */
export function aiBadgeImageRenderer(
  ids: readonly string[],
  locale: Locale = "pl",
): BlockImageRenderer {
  const generated = new Set(ids);
  return (image, element) =>
    generated.has(image.asset_id) ? withAiBadge(element, locale) : element;
}
