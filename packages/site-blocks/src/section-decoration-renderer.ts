import { createElement as h, type ReactElement, type ReactNode } from "react";
import type { SectionDecorationV1 } from "./types";

type Ornament = NonNullable<SectionDecorationV1["ornament"]>;

/** Fixed, local SVG geometry; published decoration data contains only enum values. */
function ornamentArtwork(ornament: Ornament): ReactElement {
  let shapes: ReactNode;
  if (ornament === "orbs") {
    shapes = [
      h("circle", { key: 1, cx: 162, cy: 72, r: 68 }),
      h("circle", { key: 2, cx: 83, cy: 146, r: 48, opacity: 0.6 }),
      h("circle", { key: 3, cx: 193, cy: 187, r: 28, opacity: 0.4 }),
    ];
  } else if (ornament === "rings") {
    shapes = [48, 76, 104].map((r) =>
      h("circle", {
        key: r,
        cx: 166,
        cy: 74,
        r,
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 2,
      }),
    );
  } else if (ornament === "wave") {
    shapes = [
      "M4 94C44 10 100 170 148 76S218 52 240 10",
      "M4 132C44 48 100 208 148 114S218 90 240 48",
      "M4 170C44 86 100 246 148 152S218 128 240 86",
    ].map((d) =>
      h("path", {
        key: d,
        d,
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 3,
        strokeLinecap: "round",
      }),
    );
  } else if (ornament === "botanical") {
    shapes = [
      h("path", {
        key: "stem",
        d: "M36 226Q94 158 160 22",
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 3,
      }),
      ...[
        "M60 194Q4 168 32 132Q70 142 60 194Z",
        "M76 171Q108 119 140 141Q128 179 76 171Z",
        "M103 125Q48 111 66 74Q111 80 103 125Z",
        "M120 94Q147 39 181 62Q166 98 120 94Z",
        "M142 52Q116 17 142 4Q168 18 142 52Z",
      ].map((d) => h("path", { key: d, d })),
    ];
  } else {
    shapes = [
      h("path", {
        key: "large",
        d: "M151 18L164 67L213 80L164 93L151 142L138 93L89 80L138 67Z",
      }),
      h("path", {
        key: "small",
        d: "M68 136L76 162L102 170L76 178L68 204L60 178L34 170L60 162Z",
      }),
      h("circle", { key: "dot", cx: 188, cy: 189, r: 7 }),
    ];
  }
  return h(
    "svg",
    {
      className: "site-decoration__art",
      viewBox: "0 0 240 240",
      fill: "currentColor",
      "aria-hidden": true,
      focusable: false,
    },
    shapes,
  );
}

function pauseControl(locale: "pl" | "en"): ReactElement {
  const label =
    locale === "pl"
      ? "Wstrzymaj animację dekoracji"
      : "Pause decorative animation";
  return h(
    "label",
    { className: "site-decoration__pause", title: label },
    h("input", {
      type: "checkbox",
      className: "site-decoration__pause-input",
      "aria-label": label,
    }),
    h(
      "svg",
      {
        viewBox: "0 0 24 24",
        width: 20,
        height: 20,
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 2,
        "aria-hidden": true,
        focusable: false,
      },
      h("path", {
        className: "site-decoration__pause-icon",
        d: "M8 5V19M16 5V19",
      }),
      h("path", {
        className: "site-decoration__play-icon",
        d: "M8 5L19 12L8 19Z",
      }),
    ),
  );
}

export function decorateSection(
  content: ReactElement,
  decoration: SectionDecorationV1 | undefined,
  options: { preview?: boolean; locale?: "pl" | "en" } = {},
  key?: string,
): ReactElement {
  if (!decoration) return content;
  const background = decoration.background ?? "none";
  const frame = decoration.frame ?? "none";
  const ornament = decoration.ornament ?? "none";
  if (background === "none" && frame === "none" && ornament === "none")
    return content;
  const preview = options.preview ?? true;
  const placement = decoration.placement ?? "top_right";
  const intensity = decoration.intensity ?? "subtle";
  const motion =
    !preview && ornament !== "none" ? (decoration.motion ?? "none") : "none";
  const positions =
    placement === "both" ? ["top_right", "bottom_left"] : [placement];
  return h(
    "div",
    {
      key,
      className: `site-decoration site-decoration--bg-${background} site-decoration--frame-${frame} site-decoration--${intensity} site-decoration--motion-${motion}${preview ? " site-decoration--preview" : ""}${motion !== "none" ? " site-decoration--has-control" : ""}`,
      "data-section-decoration": "1",
    },
    background !== "none"
      ? h("div", {
          className: "site-decoration__background",
          "aria-hidden": true,
        })
      : null,
    ornament !== "none"
      ? positions.map((position) =>
          h(
            "div",
            {
              key: position,
              className: `site-decoration__ornament site-decoration__ornament--${position}`,
              "aria-hidden": true,
            },
            ornamentArtwork(ornament),
          ),
        )
      : null,
    h("div", { className: "site-decoration__content" }, content),
    motion !== "none" ? pauseControl(options.locale ?? "pl") : null,
  );
}
