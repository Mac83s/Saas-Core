import { createElement as h, type ReactElement } from "react";
import type { BlockComponentProps, JsonObject } from "./types";

export type SeparatorV1Data = JsonObject & {
  layout?:
    | "space"
    | "line"
    | "double"
    | "dots"
    | "wave"
    | "curve"
    | "zigzag"
    | "accent";
  size?: "small" | "medium" | "large";
  width?: "full" | "content" | "short";
  tone?: "muted" | "accent";
};

/** Fixed artwork only: the block contract cannot provide SVG paths or markup. */
const paths = {
  wave: "M0 40C100 0 200 0 300 40S500 80 600 40S800 0 900 40S1100 80 1200 40",
  curve: "M0 4Q600 148 1200 4",
  zigzag:
    "M0 60L60 20L120 60L180 20L240 60L300 20L360 60L420 20L480 60L540 20L600 60L660 20L720 60L780 20L840 60L900 20L960 60L1020 20L1080 60L1140 20L1200 60",
} as const;

export function SeparatorBlock({ data }: BlockComponentProps): ReactElement {
  const separator = data as SeparatorV1Data;
  const layout = separator.layout ?? "line";
  const size = separator.size ?? "medium";
  const width = separator.width ?? "content";
  const tone = separator.tone ?? "muted";
  let artwork: ReactElement | null = null;

  if (layout === "wave" || layout === "curve" || layout === "zigzag") {
    artwork = h(
      "svg",
      {
        className: "site-separator__shape",
        viewBox: "0 0 1200 80",
        preserveAspectRatio: "none",
        "aria-hidden": true,
        focusable: false,
        fill: "none",
      },
      h("path", {
        d: paths[layout],
        stroke: "currentColor",
        strokeWidth: 2,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        vectorEffect: "non-scaling-stroke",
      }),
    );
  } else if (layout === "dots") {
    artwork = h(
      "span",
      { className: "site-separator__dots" },
      ...Array.from({ length: 5 }, (_, index) =>
        h("span", { key: index, className: "site-separator__dot" }),
      ),
    );
  } else if (layout !== "space") {
    artwork = h("span", { className: "site-separator__rule" });
  }

  return h(
    "div",
    {
      className: `site-block site-separator site-separator--${layout} site-separator--${size} site-separator--${width} site-separator--tone-${tone}`,
      "data-block-type": "core.separator",
      "data-section-layout": layout,
      "aria-hidden": true,
    },
    artwork
      ? h("div", { className: "site-separator__artwork" }, artwork)
      : null,
  );
}
