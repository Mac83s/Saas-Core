import { createElement as h, type ReactElement } from "react";
import { plainBlockText } from "./block-text";
import { linkRel } from "./link-rel";
import { renderImage } from "./ai-badge";
import type {
  BlockComponentProps,
  ContactV2Data,
  LinkListV1Data,
} from "./types";

type IconName =
  | "mail"
  | "phone"
  | "location"
  | "clock"
  | "link"
  | "arrow"
  | "facebook"
  | "instagram"
  | "linkedin"
  | "youtube"
  | "x"
  | "whatsapp";

/** Fixed artwork belongs to the renderer. Block data never supplies SVG or HTML. */
function icon(name: IconName): ReactElement {
  const paths: Partial<Record<IconName, string>> = {
    mail: "M3 5h18v14H3z M3 5l9 8 9-8",
    phone:
      "M6 3h4l1 5-3 2a13 13 0 0 0 6 6l2-3 5 1v4a3 3 0 0 1-3 3C10 21 3 14 3 6a3 3 0 0 1 3-3z",
    location:
      "M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0z M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    link: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
    arrow: "M5 12h14 M13 6l6 6-6 6",
    facebook: "M14 21v-8h3l1-4h-4V7c0-1 .5-2 2-2h2V1h-3c-4 0-6 2-6 6v2H6v4h3v8",
    linkedin: "M4 10v10 M4 4v1 M10 20V10 M10 14c0-5 9-5 9 0v6",
    x: "M4 3l16 18h-4L1 3h3 M20 3L4 21",
    whatsapp:
      "M4 17a9 9 0 1 1 3 3l-5 2 2-5 M8 7c0 5 4 9 9 9l1-3-3-1-1 2a8 8 0 0 1-4-4l2-1-1-3z",
  };
  const attributes = {
    viewBox: "0 0 24 24",
    width: 24,
    height: 24,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    "data-site-icon": name,
  };
  if (name === "instagram")
    return h(
      "svg",
      attributes,
      h("rect", { x: 3, y: 3, width: 18, height: 18, rx: 5 }),
      h("circle", { cx: 12, cy: 12, r: 4 }),
      h("circle", {
        cx: 17.5,
        cy: 6.5,
        r: 0.7,
        fill: "currentColor",
        stroke: "none",
      }),
    );
  if (name === "youtube")
    return h(
      "svg",
      attributes,
      h("rect", { x: 2, y: 5, width: 20, height: 14, rx: 4 }),
      h("path", { d: "M10 9l6 3-6 3z", fill: "currentColor", stroke: "none" }),
    );
  return h("svg", attributes, h("path", { d: paths[name] }));
}

const socialHosts: Readonly<Record<string, IconName>> = {
  "facebook.com": "facebook",
  "m.facebook.com": "facebook",
  "instagram.com": "instagram",
  "linkedin.com": "linkedin",
  "youtube.com": "youtube",
  "youtu.be": "youtube",
  "x.com": "x",
  "twitter.com": "x",
  "wa.me": "whatsapp",
  "whatsapp.com": "whatsapp",
  "api.whatsapp.com": "whatsapp",
};
function linkIcon(href: string): IconName {
  if (href.startsWith("mailto:")) return "mail";
  if (href.startsWith("tel:")) return "phone";
  if (!href.startsWith("https://")) return "link";
  try {
    const hostname = new URL(href).hostname.toLowerCase().replace(/^www\./, "");
    return socialHosts[hostname] ?? "link";
  } catch {
    return "link";
  }
}

export function ContactSection({
  data,
  editor,
  imageRenderer,
}: BlockComponentProps) {
  const contact = data as ContactV2Data;
  const text = editor?.text ?? plainBlockText;
  const layout = contact.layout ?? "classic";
  const rows = [
    {
      key: "email",
      icon: "mail",
      value: contact.email,
      href: contact.email ? `mailto:${contact.email}` : undefined,
    },
    {
      key: "phone",
      icon: "phone",
      value: contact.phone,
      href: contact.phone
        ? `tel:${contact.phone.replace(/[^0-9+]/g, "")}`
        : undefined,
    },
    { key: "address", icon: "location", value: contact.address },
    { key: "hours", icon: "clock", value: contact.hours },
  ] as const;
  return h(
    "section",
    {
      className: `site-block site-contact site-contact--${layout}`,
      "data-block-type": "core.contact",
      "data-section-layout": layout,
    },
    h(
      "div",
      { className: "site-contact__intro" },
      contact.title
        ? h(
            "h2",
            editor ? { role: "presentation" } : null,
            text(["title"], contact.title),
          )
        : null,
      contact.text ? h("p", null, text(["text"], contact.text)) : null,
    ),
    contact.image
      ? h(
          "div",
          { className: "site-contact__photo" },
          renderImage(
            contact.image,
            h("img", {
              src: `/media/${contact.image.asset_id}`,
              alt: contact.image.alt,
              loading: "lazy",
              decoding: "async",
            }),
            imageRenderer,
          ),
        )
      : null,
    h(
      "address",
      { className: "site-contact__details" },
      rows.map((row) =>
        row.value
          ? h(
              "div",
              {
                className: `site-contact__item site-contact__item--${row.key}`,
                key: row.key,
              },
              icon(row.icon),
              "href" in row && row.href && !editor
                ? h("a", { href: row.href }, text([row.key], row.value))
                : h("span", null, text([row.key], row.value)),
            )
          : null,
      ),
    ),
    contact.action
      ? h(
          "div",
          { className: "site-contact__action" },
          h(
            editor ? "span" : "a",
            {
              className: "site-section__action",
              href: editor ? undefined : contact.action.href,
              rel:
                !editor && contact.action.href.startsWith("https://")
                  ? "noreferrer"
                  : undefined,
            },
            text(["action", "label"], contact.action.label),
            icon("arrow"),
          ),
        )
      : null,
  );
}

export function LinkListSection({ data, editor }: BlockComponentProps) {
  const links = data as LinkListV1Data;
  const text = editor?.text ?? plainBlockText;
  const layout = links.layout ?? "buttons";
  return h(
    "section",
    {
      className: `site-block site-links site-links--${layout}`,
      "data-block-type": "core.link_list",
      "data-section-layout": layout,
    },
    h(
      "div",
      { className: "site-links__intro" },
      links.title
        ? h(
            "h2",
            editor ? { role: "presentation" } : null,
            text(["title"], links.title),
          )
        : null,
      links.text ? h("p", null, text(["text"], links.text)) : null,
    ),
    h(
      "ul",
      { className: "site-links__items" },
      links.links.map((link, i) =>
        h(
          "li",
          { key: i },
          h(
            editor ? "div" : "a",
            {
              className: "site-links__link",
              href: editor ? undefined : link.href,
              rel: editor ? undefined : linkRel(link.href, link.rel),
            },
            h(
              "span",
              { className: "site-links__icon" },
              icon(linkIcon(link.href)),
            ),
            h(
              "span",
              { className: "site-links__copy" },
              h(
                "span",
                { className: "site-links__label" },
                text(["links", String(i), "label"], link.label),
              ),
              link.description
                ? h(
                    "span",
                    { className: "site-links__description" },
                    text(["links", String(i), "description"], link.description),
                  )
                : null,
            ),
            h("span", { className: "site-links__arrow" }, icon("arrow")),
          ),
        ),
      ),
    ),
  );
}
