import separatorV1Schema from "@saas-core/contracts/site-blocks/core.separator.v1.schema.json";
import { SeparatorBlock } from "./separator-block";
import contactFormV1Schema from "@saas-core/contracts/site-blocks/core.contact_form.v1.schema.json";
import contactFormV2Schema from "@saas-core/contracts/site-blocks/core.contact_form.v2.schema.json";
import { ContactFormSection } from "./contact-form-block";
import heroV5Schema from "@saas-core/contracts/site-blocks/core.hero.v5.schema.json";
import featureListV3Schema from "@saas-core/contracts/site-blocks/core.feature_list.v3.schema.json";
import faqV3Schema from "@saas-core/contracts/site-blocks/core.faq.v3.schema.json";
import heroV4Schema from "@saas-core/contracts/site-blocks/core.hero.v4.schema.json";
import heroV6Schema from "@saas-core/contracts/site-blocks/core.hero.v6.schema.json";
import featureListV2Schema from "@saas-core/contracts/site-blocks/core.feature_list.v2.schema.json";
import faqV2Schema from "@saas-core/contracts/site-blocks/core.faq.v2.schema.json";
import featureListV4Schema from "@saas-core/contracts/site-blocks/core.feature_list.v4.schema.json";
import featureListV5Schema from "@saas-core/contracts/site-blocks/core.feature_list.v5.schema.json";
import richTextV2Schema from "@saas-core/contracts/site-blocks/core.rich_text.v2.schema.json";
import richTextV3Schema from "@saas-core/contracts/site-blocks/core.rich_text.v3.schema.json";
import richTextV4Schema from "@saas-core/contracts/site-blocks/core.rich_text.v4.schema.json";
import quoteV1Schema from "@saas-core/contracts/site-blocks/core.quote.v1.schema.json";
import quoteV2Schema from "@saas-core/contracts/site-blocks/core.quote.v2.schema.json";
import galleryV1Schema from "@saas-core/contracts/site-blocks/core.gallery.v1.schema.json";
import productV1Schema from "@saas-core/contracts/site-blocks/core.product.v1.schema.json";
import productV2Schema from "@saas-core/contracts/site-blocks/core.product.v2.schema.json";
import productV3Schema from "@saas-core/contracts/site-blocks/core.product.v3.schema.json";
import { plainBlockText } from "./block-text";
import { QuoteBlock, withSecondaryAction } from "./editorial-blocks";
import {
  migrateRichTextV1ToV2,
  migrateRichTextV2ToV3,
  migrateRichTextV3ToV4,
  RichTextBlock,
} from "./rich-text-block";
import {
  featureListIntro,
  featureListNote,
  renderSectionLayout,
} from "./section-layouts";
import { featureListAction } from "./feature-list-layouts";
import { ContactSection, LinkListSection } from "./contact-link-sections";
import { createElement } from "react";
import { renderImage } from "./ai-badge";
import { FULL_WIDTH, publicImage } from "./public-image";
import { GalleryBlock } from "./gallery-block";
import { ProductV3Block } from "./product-layouts";

import contactV1Schema from "@saas-core/contracts/site-blocks/core.contact.v1.schema.json";
import contactV2Schema from "@saas-core/contracts/site-blocks/core.contact.v2.schema.json";
import linkListV1Schema from "@saas-core/contracts/site-blocks/core.link_list.v1.schema.json";
import linkListV2Schema from "@saas-core/contracts/site-blocks/core.link_list.v2.schema.json";
import entryListV1Schema from "@saas-core/contracts/site-blocks/core.entry_list.v1.schema.json";
import bookingV1Schema from "@saas-core/contracts/site-blocks/core.booking.v1.schema.json";
import stayCalendarV1Schema from "@saas-core/contracts/site-blocks/core.stay_calendar.v1.schema.json";
import staySearchV1Schema from "@saas-core/contracts/site-blocks/core.stay_search.v1.schema.json";
import stayMapV1Schema from "@saas-core/contracts/site-blocks/core.stay_map.v1.schema.json";
import stayUnitV1Schema from "@saas-core/contracts/site-blocks/core.stay_unit.v1.schema.json";
import stayUnitsV1Schema from "@saas-core/contracts/site-blocks/core.stay_units.v1.schema.json";
import faqV1Schema from "@saas-core/contracts/site-blocks/core.faq.v1.schema.json";
import featureListV1Schema from "@saas-core/contracts/site-blocks/core.feature_list.v1.schema.json";
import footerV1Schema from "@saas-core/contracts/site-blocks/core.footer.v1.schema.json";
import footerV2Schema from "@saas-core/contracts/site-blocks/core.footer.v2.schema.json";
import heroV1Schema from "@saas-core/contracts/site-blocks/core.hero.v1.schema.json";
import heroV2Schema from "@saas-core/contracts/site-blocks/core.hero.v2.schema.json";
import heroV3Schema from "@saas-core/contracts/site-blocks/core.hero.v3.schema.json";
import pricingV1Schema from "@saas-core/contracts/site-blocks/core.pricing.v1.schema.json";
import richTextV1Schema from "@saas-core/contracts/site-blocks/core.rich_text.v1.schema.json";
import testimonialsV1Schema from "@saas-core/contracts/site-blocks/core.testimonials.v1.schema.json";

import { linkRel } from "./link-rel";
import {
  StayCalendarBlock,
  StaySearchBlock,
  StayMapBlock,
  StayUnitBlock,
  StayUnitsBlock,
} from "./stay-blocks";
import type {
  BlockComponentProps,
  BlockFieldDefinition,
  BookingV1Data,
  ContactV1Data,
  EntryListV1Data,
  FaqV1Data,
  FeatureListV5Data,
  FooterV1Data,
  HeroV1Data,
  HeroV2Data,
  HeroV6Data,
  JsonObject,
  PricingV1Data,
  SiteBlockManifest,
  TestimonialsV1Data,
} from "./types";

function externalRel(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

/** How a link vouches for its target (ADR-061). The empty first option is an
 *  editorial link: nothing stored, the way every link rendered before. */
const LINK_REL_FIELD: BlockFieldDefinition = {
  path: ["rel"],
  kind: "choice",
  labelKey: "linkRel",
  options: ["", "sponsored", "ugc", "nofollow"],
};

/** The address a published asset is served from on the site's own host.
 *
 *  Root-relative on purpose: a published page is rendered under the visitor's
 *  hostname, and baking an origin in would break the moment a client moves to
 *  their own domain. */
export function publicMediaPath(assetId: string): string {
  return `/media/${assetId}`;
}

function HeroBlock({ data, editor, imageRenderer }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const variant = renderSectionLayout("core.hero", data, editor, imageRenderer);
  if (variant) return variant;
  const hero = data as HeroV6Data;
  const action = hero.action;
  return createElement(
    "section",
    {
      className: "site-block site-block--hero",
      "data-block-type": "core.hero",
    },
    createElement(
      "h1",
      editor ? { role: "presentation" } : null,
      text(["title"], hero.title),
    ),
    hero.image
      ? renderImage(
          hero.image,
          // A hero is the first thing on the page, so it is the one image
          // worth fetching eagerly; everything else can wait.
          publicImage(hero.image, { sizes: FULL_WIDTH, loading: "eager" }),
          imageRenderer,
        )
      : null,
    hero.text ? createElement("p", null, text(["text"], hero.text)) : null,
    withSecondaryAction(
      action
        ? createElement(
            editor ? "span" : "a",
            {
              className: "site-section__action",
              href: editor ? undefined : action.href,
              rel: editor ? undefined : externalRel(action.href),
            },
            text(["action", "label"], action.label),
          )
        : null,
      hero.secondaryAction,
      text,
      editor,
    ),
  );
}

function FeatureListBlock({
  data,
  editor,
  imageRenderer,
}: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const variant = renderSectionLayout(
    "core.feature_list",
    data,
    editor,
    imageRenderer,
  );
  if (variant) return variant;
  const featureList = data as FeatureListV5Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--feature-list",
      "data-block-type": "core.feature_list",
    },
    featureListIntro(featureList, text, editor),
    createElement(
      "ul",
      null,
      featureList.items.map((item, index) =>
        createElement(
          "li",
          { key: index },
          createElement(
            "h3",
            editor ? { role: "presentation" } : null,
            text(["items", String(index), "title"], item.title),
          ),
          item.text
            ? createElement(
                "p",
                null,
                text(["items", String(index), "text"], item.text),
              )
            : null,
        ),
      ),
    ),
    featureListNote(featureList, text, editor),
    featureListAction(featureList, text, editor),
  );
}

function FaqBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const variant = renderSectionLayout("core.faq", data, editor);
  if (variant) return variant;
  const faq = data as FaqV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--faq",
      "data-block-type": "core.faq",
    },
    faq.title
      ? createElement(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], faq.title),
        )
      : null,
    createElement(
      "dl",
      null,
      faq.items.flatMap((item, index) => [
        createElement(
          "dt",
          { key: `q-${index}` },
          text(["items", String(index), "question"], item.question),
        ),
        createElement(
          "dd",
          { key: `a-${index}` },
          text(["items", String(index), "answer"], item.answer),
        ),
      ]),
    ),
  );
}

function ContactBlock({ data, editor, imageRenderer }: BlockComponentProps) {
  // Old publications retain their original markup until a new layout or field
  // is chosen. The v1 -> v2 migration itself does not redesign a saved page.
  if (data.layout || data.text || data.hours || data.image || data.action)
    return createElement(ContactSection, { data, editor, imageRenderer });
  const text = editor?.text ?? plainBlockText;
  const contact = data as ContactV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--contact",
      "data-block-type": "core.contact",
    },
    contact.title
      ? createElement(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], contact.title),
        )
      : null,
    createElement(
      "address",
      null,
      contact.email
        ? createElement(
            editor ? "span" : "a",
            { href: editor ? undefined : `mailto:${contact.email}` },
            text(["email"], contact.email),
          )
        : null,
      contact.phone
        ? createElement(
            editor ? "span" : "a",
            {
              href: editor
                ? undefined
                : `tel:${contact.phone.replace(/[^0-9+]/g, "")}`,
            },
            text(["phone"], contact.phone),
          )
        : null,
      contact.address
        ? createElement("p", null, text(["address"], contact.address))
        : null,
    ),
  );
}

function TestimonialsBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const testimonials = data as TestimonialsV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--testimonials",
      "data-block-type": "core.testimonials",
    },
    testimonials.title
      ? createElement(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], testimonials.title),
        )
      : null,
    createElement(
      "ul",
      null,
      testimonials.items.map((item, index) =>
        createElement(
          "li",
          { key: index },
          createElement(
            "blockquote",
            null,
            createElement(
              "p",
              null,
              text(["items", String(index), "quote"], item.quote),
            ),
            createElement(
              "footer",
              null,
              createElement(
                "cite",
                null,
                text(["items", String(index), "author"], item.author),
              ),
              item.role
                ? createElement(
                    "span",
                    null,
                    text(["items", String(index), "role"], item.role),
                  )
                : null,
            ),
          ),
        ),
      ),
    ),
  );
}

function PricingBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const pricing = data as PricingV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--pricing",
      "data-block-type": "core.pricing",
    },
    pricing.title
      ? createElement(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], pricing.title),
        )
      : null,
    createElement(
      "ul",
      null,
      pricing.items.map((item, index) =>
        createElement(
          "li",
          { key: index },
          createElement(
            "article",
            null,
            createElement(
              "h3",
              editor ? { role: "presentation" } : null,
              text(["items", String(index), "name"], item.name),
            ),
            createElement(
              "p",
              { className: "site-block__price" },
              text(["items", String(index), "price"], item.price),
            ),
            item.description
              ? createElement(
                  "p",
                  null,
                  text(
                    ["items", String(index), "description"],
                    item.description,
                  ),
                )
              : null,
          ),
        ),
      ),
    ),
  );
}

function BookingBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const booking = data as BookingV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--booking",
      "data-block-type": "core.booking",
    },
    createElement(
      "h2",
      editor ? { role: "presentation" } : null,
      text(["title"], booking.title),
    ),
    booking.text
      ? createElement("p", null, text(["text"], booking.text))
      : null,
    createElement(
      editor ? "span" : "a",
      {
        className: "site-section__action",
        href: editor ? undefined : booking.action.href,
        rel: editor ? undefined : externalRel(booking.action.href),
      },
      text(["action", "label"], booking.action.label),
    ),
  );
}

function FooterBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const footer = data as FooterV1Data;
  return createElement(
    "footer",
    {
      className: "site-block site-block--footer",
      "data-block-type": "core.footer",
    },
    createElement("p", null, text(["text"], footer.text)),
    footer.links === undefined
      ? null
      : createElement(
          "ul",
          null,
          footer.links.map((link, index) =>
            createElement(
              "li",
              { key: index },
              createElement(
                editor ? "span" : "a",
                {
                  href: editor ? undefined : link.href,
                  rel: editor ? undefined : linkRel(link.href, link.rel),
                },
                text(["links", String(index), "label"], link.label),
              ),
            ),
          ),
        ),
  );
}

/** The blog index, and any "latest posts" section an operator places by hand.
 *  The items are a projection of what is published (ADR-035 §7), so the block
 *  renders whatever it is handed rather than reaching for data itself. */
function EntryListBlock({ data, editor }: BlockComponentProps) {
  const text = editor?.text ?? plainBlockText;
  const list = data as EntryListV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--entry-list",
      "data-block-type": "core.entry_list",
    },
    list.title === undefined
      ? null
      : createElement(
          "h2",
          editor ? { role: "presentation" } : null,
          text(["title"], list.title),
        ),
    list.items.length === 0
      ? createElement("p", null, text(["empty_text"], list.empty_text ?? ""))
      : createElement(
          "ul",
          null,
          list.items.map((item, index) =>
            createElement(
              "li",
              { key: index },
              createElement(
                editor ? "span" : "a",
                { href: editor ? undefined : item.path },
                createElement(
                  "h3",
                  editor ? { role: "presentation" } : null,
                  text(["items", String(index), "title"], item.title),
                ),
              ),
              item.published_at === undefined
                ? null
                : createElement(
                    "time",
                    { dateTime: item.published_at },
                    item.published_at.slice(0, 10),
                  ),
              item.excerpt === undefined
                ? null
                : createElement(
                    "p",
                    null,
                    text(["items", String(index), "excerpt"], item.excerpt),
                  ),
            ),
          ),
        ),
  );
}

function migrateHeroV1ToV2(data: Readonly<JsonObject>): JsonObject {
  const hero = data as HeroV1Data;
  const migrated: HeroV2Data = { title: hero.heading };
  if (hero.body !== undefined) {
    migrated.text = hero.body;
  }
  if (hero.ctaLabel !== undefined && hero.ctaHref !== undefined) {
    migrated.action = { label: hero.ctaLabel, href: hero.ctaHref };
  }
  return migrated;
}

/** v2 already carries everything v3 requires: the picture is optional, so a
 *  hero saved before images existed migrates by staying exactly as it is. */
function migrateHeroV2ToV3(data: Readonly<JsonObject>): JsonObject {
  return { ...data };
}

export const coreSiteBlockManifest: SiteBlockManifest = {
  moduleId: "shared.sites",
  namespace: "core",
  blocks: [
    {
      type: "core.separator",
      latestVersion: 1,
      schemas: [{ version: 1, schema: separatorV1Schema }],
      migrators: {},
      component: SeparatorBlock,
      catalog: {
        category: "decorative",
        labelKey: "separatorBlock",
        fields: [],
      },
    },
    {
      type: "core.hero",
      latestVersion: 6,
      schemas: [
        { version: 1, schema: heroV1Schema },
        { version: 2, schema: heroV2Schema },
        { version: 3, schema: heroV3Schema },
        { version: 4, schema: heroV4Schema },
        { version: 5, schema: heroV5Schema },
        { version: 6, schema: heroV6Schema },
      ],
      migrators: {
        1: migrateHeroV1ToV2,
        2: migrateHeroV2ToV3,
        3: (data) => ({ ...data }),
        4: (data) => ({ ...data }),
        5: (data) => ({ ...data }),
      },
      component: HeroBlock,
      catalog: {
        category: "start",
        labelKey: "heroBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            // Pierwszy ekran strony: szeroki kadr filmowy.
            aspect: [16, 9],
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
          {
            path: ["secondaryAction", "label"],
            kind: "text",
            labelKey: "secondaryActionLabel",
          },
          {
            path: ["secondaryAction", "href"],
            kind: "url",
            labelKey: "secondaryActionHref",
          },
        ],
      },
    },
    {
      type: "core.rich_text",
      latestVersion: 4,
      schemas: [
        { version: 1, schema: richTextV1Schema },
        { version: 2, schema: richTextV2Schema },
        { version: 3, schema: richTextV3Schema },
        { version: 4, schema: richTextV4Schema },
      ],
      migrators: {
        1: migrateRichTextV1ToV2,
        2: migrateRichTextV2ToV3,
        3: migrateRichTextV3ToV4,
      },
      component: RichTextBlock,
      catalog: {
        category: "about",
        labelKey: "richTextBlock",
        fields: [
          { path: ["eyebrow"], kind: "text", labelKey: "eyebrow" },
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["lead"], kind: "textarea", labelKey: "lead" },
          {
            path: ["content"],
            kind: "richText",
            labelKey: "richTextContent",
          },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            // Zdjęcie obok tekstu, panorama albo ilustracja w toku czytania.
            aspect: [4, 3],
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
          {
            path: ["image", "caption"],
            kind: "text",
            labelKey: "imageCaption",
          },
          { path: ["author", "name"], kind: "text", labelKey: "authorName" },
          { path: ["author", "role"], kind: "text", labelKey: "authorRole" },
          {
            path: ["author", "image", "asset_id"],
            kind: "media",
            labelKey: "authorPhoto",
            // Portret na karcie autora: kwadrat, w kółku.
            aspect: [1, 1],
            // Evidence of a real person: no AI images (ADR-059 pkt 8).
            realMediaOnly: true,
          },
          {
            path: ["author", "image", "alt"],
            kind: "text",
            labelKey: "imageAlt",
          },
          { path: ["aside", "title"], kind: "text", labelKey: "asideTitle" },
          {
            path: ["aside", "content"],
            kind: "richText",
            labelKey: "asideContent",
          },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
          {
            path: ["secondaryAction", "label"],
            kind: "text",
            labelKey: "secondaryActionLabel",
          },
          {
            path: ["secondaryAction", "href"],
            kind: "url",
            labelKey: "secondaryActionHref",
          },
        ],
      },
    },
    {
      type: "core.feature_list",
      latestVersion: 5,
      schemas: [
        { version: 1, schema: featureListV1Schema },
        { version: 2, schema: featureListV2Schema },
        { version: 3, schema: featureListV3Schema },
        { version: 4, schema: featureListV4Schema },
        { version: 5, schema: featureListV5Schema },
      ],
      migrators: {
        1: (data) => ({ ...data }),
        2: (data) => ({ ...data }),
        // v4 only adds optional fields (lead, note) and two layouts.
        3: (data) => ({ ...data }),
        // v5 only adds optional fields (columns, action, an item's group,
        // note and values) and six layouts.
        4: (data) => ({ ...data }),
      },
      component: FeatureListBlock,
      catalog: {
        category: "offer",
        labelKey: "featureListBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["lead"], kind: "textarea", labelKey: "lead" },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            // Obok listy cech: kadr bliżej kwadratu trzyma wysokość sekcji.
            aspect: [4, 3],
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
          {
            path: ["columns"],
            kind: "list",
            labelKey: "featureColumns",
            item: [
              { path: ["title"], kind: "text", labelKey: "columnTitle" },
              { path: ["text"], kind: "textarea", labelKey: "columnText" },
            ],
          },
          {
            path: ["items"],
            kind: "list",
            labelKey: "featureItems",
            item: [
              { path: ["group"], kind: "text", labelKey: "itemGroup" },
              { path: ["title"], kind: "text", labelKey: "featureTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
              {
                path: ["values", "first"],
                kind: "text",
                labelKey: "itemValueFirst",
              },
              {
                path: ["values", "second"],
                kind: "text",
                labelKey: "itemValueSecond",
              },
              {
                path: ["values", "third"],
                kind: "text",
                labelKey: "itemValueThird",
              },
              { path: ["note"], kind: "textarea", labelKey: "itemNote" },
            ],
          },
          { path: ["note", "title"], kind: "text", labelKey: "noteTitle" },
          { path: ["note", "text"], kind: "textarea", labelKey: "noteText" },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    {
      type: "core.faq",
      latestVersion: 3,
      schemas: [
        { version: 1, schema: faqV1Schema },
        { version: 2, schema: faqV2Schema },
        { version: 3, schema: faqV3Schema },
      ],
      migrators: { 1: (data) => ({ ...data }), 2: (data) => ({ ...data }) },
      component: FaqBlock,
      catalog: {
        category: "faq",
        labelKey: "faqBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          {
            path: ["items"],
            kind: "list",
            labelKey: "faqItems",
            item: [
              { path: ["question"], kind: "text", labelKey: "faqQuestion" },
              { path: ["answer"], kind: "textarea", labelKey: "faqAnswer" },
            ],
          },
        ],
      },
    },
    {
      type: "core.contact",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: contactV1Schema },
        { version: 2, schema: contactV2Schema },
      ],
      migrators: { 1: (data) => ({ ...data }) },
      component: ContactBlock,
      catalog: {
        category: "contact",
        labelKey: "contactBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["email"], kind: "text", labelKey: "contactEmail" },
          { path: ["phone"], kind: "text", labelKey: "contactPhone" },
          { path: ["address"], kind: "textarea", labelKey: "contactAddress" },
          { path: ["hours"], kind: "textarea", labelKey: "contactHours" },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            aspect: [4, 3],
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    {
      type: "core.contact_form",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: contactFormV1Schema },
        { version: 2, schema: contactFormV2Schema },
      ],
      // v2 only adds `contact`; absent, the form behaves exactly as v1.
      migrators: { 1: (data) => ({ ...data }) },
      component: ContactFormSection,
      catalog: {
        category: "contact",
        labelKey: "contactFormBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          {
            path: ["contact"],
            kind: "choice",
            labelKey: "contactMode",
            options: ["email", "callback", "full", "email_only"],
          },
          { path: ["submit_label"], kind: "text", labelKey: "submitLabel" },
          {
            path: ["success_message"],
            kind: "textarea",
            labelKey: "successMessage",
          },
          { path: ["privacy_label"], kind: "text", labelKey: "privacyLabel" },
          { path: ["privacy_href"], kind: "url", labelKey: "privacyHref" },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            aspect: [4, 3],
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
        ],
      },
    },
    {
      type: "core.link_list",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: linkListV1Schema },
        { version: 2, schema: linkListV2Schema },
      ],
      // v2 only adds the optional `rel` (ADR-061).
      migrators: { 1: (data) => ({ ...data }) },
      component: LinkListSection,
      catalog: {
        category: "contact",
        labelKey: "linkListBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          {
            path: ["links"],
            kind: "list",
            labelKey: "linkItems",
            item: [
              { path: ["label"], kind: "text", labelKey: "linkLabel" },
              { path: ["href"], kind: "url", labelKey: "linkHref" },
              LINK_REL_FIELD,
              {
                path: ["description"],
                kind: "textarea",
                labelKey: "linkDescription",
              },
            ],
          },
        ],
      },
    },
    {
      type: "core.testimonials",
      latestVersion: 1,
      schemas: [{ version: 1, schema: testimonialsV1Schema }],
      migrators: {},
      component: TestimonialsBlock,
      catalog: {
        category: "trust",
        labelKey: "testimonialsBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          {
            path: ["items"],
            kind: "list",
            labelKey: "testimonialItems",
            item: [
              {
                path: ["quote"],
                kind: "textarea",
                labelKey: "testimonialQuote",
              },
              { path: ["author"], kind: "text", labelKey: "testimonialAuthor" },
              { path: ["role"], kind: "text", labelKey: "testimonialRole" },
            ],
          },
        ],
      },
    },
    {
      type: "core.pricing",
      latestVersion: 1,
      schemas: [{ version: 1, schema: pricingV1Schema }],
      migrators: {},
      component: PricingBlock,
      catalog: {
        category: "pricing",
        labelKey: "pricingBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          {
            path: ["items"],
            kind: "list",
            labelKey: "pricingItems",
            item: [
              { path: ["name"], kind: "text", labelKey: "pricingName" },
              { path: ["price"], kind: "text", labelKey: "pricingPrice" },
              {
                path: ["description"],
                kind: "textarea",
                labelKey: "pricingDescription",
              },
            ],
          },
        ],
      },
    },
    {
      type: "core.booking",
      latestVersion: 1,
      schemas: [{ version: 1, schema: bookingV1Schema }],
      migrators: {},
      component: BookingBlock,
      catalog: {
        category: "booking",
        labelKey: "bookingBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    // The three blocks of offers booked from–to (ADR-072, slice 5d): each
    // carries a choice, and a published page fills it from the company's
    // booking at every read.
    {
      type: "core.stay_units",
      latestVersion: 1,
      schemas: [{ version: 1, schema: stayUnitsV1Schema }],
      migrators: {},
      component: StayUnitsBlock,
      live: true,
      catalog: {
        category: "booking",
        labelKey: "stayUnitsBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["offer"], kind: "stayOffer", labelKey: "stayOffer" },
          {
            path: ["layout"],
            kind: "choice",
            labelKey: "stayUnitsLayout",
            options: ["cards", "rows"],
          },
          { path: ["action_label"], kind: "text", labelKey: "actionLabel" },
        ],
      },
    },
    {
      type: "core.stay_search",
      latestVersion: 1,
      schemas: [{ version: 1, schema: staySearchV1Schema }],
      migrators: {},
      component: StaySearchBlock,
      live: true,
      catalog: {
        category: "booking",
        labelKey: "staySearchBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["offer"], kind: "stayOffer", labelKey: "stayOffer" },
          { path: ["action_label"], kind: "text", labelKey: "actionLabel" },
        ],
      },
    },
    {
      type: "core.stay_calendar",
      latestVersion: 1,
      schemas: [{ version: 1, schema: stayCalendarV1Schema }],
      migrators: {},
      component: StayCalendarBlock,
      live: true,
      catalog: {
        category: "booking",
        labelKey: "stayCalendarBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["offer"], kind: "stayOffer", labelKey: "stayOffer" },
          { path: ["action_label"], kind: "text", labelKey: "actionLabel" },
        ],
      },
    },
    // One unit's card (slice 5e); the unit's own page is this block alone.
    {
      type: "core.stay_unit",
      latestVersion: 1,
      schemas: [{ version: 1, schema: stayUnitV1Schema }],
      migrators: {},
      component: StayUnitBlock,
      live: true,
      catalog: {
        category: "booking",
        labelKey: "stayUnitBlock",
        fields: [
          { path: ["unit"], kind: "stayUnit", labelKey: "stayUnit" },
          { path: ["action_label"], kind: "text", labelKey: "actionLabel" },
        ],
      },
    },
    // Where a unit is (the map block of slice 5e): its town, or its own
    // point once the company shows it. The unit's own page has it under the
    // card; the map itself loads only when the visitor asks.
    {
      type: "core.stay_map",
      latestVersion: 1,
      schemas: [{ version: 1, schema: stayMapV1Schema }],
      migrators: {},
      component: StayMapBlock,
      live: true,
      catalog: {
        category: "booking",
        labelKey: "stayMapBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["unit"], kind: "stayPlace", labelKey: "stayUnit" },
        ],
      },
    },
    {
      type: "core.entry_list",
      latestVersion: 1,
      schemas: [{ version: 1, schema: entryListV1Schema }],
      migrators: {},
      component: EntryListBlock,
      // Deliberately absent from the catalogue. ADR-031 froze the nine sections
      // an operator picks from, and this block is not one of them: it is the
      // projection the blog index is built from, filled by the server rather
      // than typed by hand. Offering it in the picker would be a change to an
      // accepted decision, which belongs in a new ADR rather than here.
    },
    {
      type: "core.footer",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: footerV1Schema },
        { version: 2, schema: footerV2Schema },
      ],
      // v2 only adds the optional `rel` (ADR-061).
      migrators: { 1: (data) => ({ ...data }) },
      component: FooterBlock,
      catalog: {
        category: "footer",
        labelKey: "footerBlock",
        fields: [
          { path: ["text"], kind: "textarea", labelKey: "footerText" },
          {
            path: ["links"],
            kind: "list",
            labelKey: "footerLinks",
            item: [
              { path: ["label"], kind: "text", labelKey: "linkLabel" },
              { path: ["href"], kind: "url", labelKey: "linkHref" },
              LINK_REL_FIELD,
            ],
          },
        ],
      },
    },
    {
      type: "core.quote",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: quoteV1Schema },
        { version: 2, schema: quoteV2Schema },
      ],
      // v2 only adds optional fields (title, voices, action) and five layouts.
      migrators: { 1: (data) => ({ ...data }) },
      component: QuoteBlock,
      catalog: {
        category: "about",
        labelKey: "quoteBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["quote"], kind: "textarea", labelKey: "quoteText" },
          { path: ["author"], kind: "text", labelKey: "quoteAuthor" },
          { path: ["role"], kind: "text", labelKey: "quoteRole" },
          {
            path: ["source", "label"],
            kind: "text",
            labelKey: "quoteSourceLabel",
          },
          {
            path: ["source", "href"],
            kind: "url",
            labelKey: "quoteSourceHref",
          },
          { path: ["context"], kind: "textarea", labelKey: "quoteContext" },
          {
            path: ["image", "asset_id"],
            kind: "media",
            labelKey: "imageAsset",
            // Portret mówcy: pionowy kadr obok cytatu.
            aspect: [4, 5],
            // A portrait beside a quote: no AI images (ADR-059 pkt 8).
            realMediaOnly: true,
          },
          { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
          {
            path: ["voices"],
            kind: "list",
            labelKey: "quoteVoices",
            maxItems: 2,
            item: [
              { path: ["quote"], kind: "textarea", labelKey: "quoteText" },
              { path: ["author"], kind: "text", labelKey: "quoteAuthor" },
              { path: ["role"], kind: "text", labelKey: "quoteRole" },
            ],
          },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    {
      type: "core.gallery",
      latestVersion: 1,
      schemas: [{ version: 1, schema: galleryV1Schema }],
      migrators: {},
      component: GalleryBlock,
      catalog: {
        category: "about",
        labelKey: "galleryBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["lead"], kind: "textarea", labelKey: "lead" },
          {
            path: ["items"],
            kind: "list",
            labelKey: "galleryItems",
            maxItems: 12,
            item: [
              {
                path: ["image", "asset_id"],
                kind: "media",
                labelKey: "imageAsset",
                // A tile's frame; the layouts crop to it.
                aspect: [4, 3],
              },
              { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
              { path: ["title"], kind: "text", labelKey: "galleryItemTitle" },
              {
                path: ["caption"],
                kind: "textarea",
                labelKey: "galleryItemCaption",
              },
              {
                path: ["link", "label"],
                kind: "text",
                labelKey: "galleryLinkLabel",
              },
              {
                path: ["link", "href"],
                kind: "url",
                labelKey: "galleryLinkHref",
              },
            ],
          },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    {
      type: "core.product",
      latestVersion: 3,
      schemas: [
        { version: 1, schema: productV1Schema },
        { version: 2, schema: productV2Schema },
        { version: 3, schema: productV3Schema },
      ],
      migrators: { 1: (data) => ({ ...data }), 2: (data) => ({ ...data }) },
      component: ProductV3Block,
      catalog: {
        category: "offer",
        labelKey: "productBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["tagline"], kind: "text", labelKey: "productTagline" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          {
            path: ["images"],
            kind: "list",
            labelKey: "productImages",
            maxItems: 8,
            item: [
              {
                path: ["asset_id"],
                kind: "media",
                labelKey: "imageAsset",
                aspect: [4, 3],
              },
              { path: ["alt"], kind: "text", labelKey: "imageAlt" },
              { path: ["caption"], kind: "text", labelKey: "imageCaption" },
            ],
          },
          {
            path: ["specs"],
            kind: "list",
            labelKey: "productSpecs",
            maxItems: 24,
            item: [
              { path: ["group"], kind: "text", labelKey: "itemGroup" },
              { path: ["label"], kind: "text", labelKey: "specLabel" },
              { path: ["value"], kind: "text", labelKey: "specValue" },
            ],
          },
          {
            path: ["uses"],
            kind: "list",
            labelKey: "productUses",
            maxItems: 8,
            item: [
              { path: ["title"], kind: "text", labelKey: "useTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
              {
                path: ["image", "asset_id"],
                kind: "media",
                labelKey: "imageAsset",
                aspect: [4, 3],
              },
              { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
            ],
          },
          {
            path: ["details"],
            kind: "list",
            labelKey: "productDetails",
            maxItems: 6,
            item: [
              { path: ["title"], kind: "text", labelKey: "detailTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
            ],
          },
          {
            path: ["included"],
            kind: "list",
            labelKey: "productIncluded",
            maxItems: 16,
            item: [
              { path: ["title"], kind: "text", labelKey: "includedTitle" },
              {
                path: ["quantity"],
                kind: "text",
                labelKey: "includedQuantity",
              },
              { path: ["text"], kind: "textarea", labelKey: "text" },
            ],
          },
          {
            path: ["variants"],
            kind: "list",
            labelKey: "productVariants",
            maxItems: 3,
            item: [
              { path: ["title"], kind: "text", labelKey: "variantTitle" },
              { path: ["fit"], kind: "text", labelKey: "variantFit" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
            ],
          },
          {
            path: ["materials"],
            kind: "list",
            labelKey: "productMaterials",
            maxItems: 8,
            item: [
              { path: ["title"], kind: "text", labelKey: "materialTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
              {
                path: ["image", "asset_id"],
                kind: "media",
                labelKey: "imageAsset",
                aspect: [1, 1],
              },
              { path: ["image", "alt"], kind: "text", labelKey: "imageAlt" },
            ],
          },
          {
            path: ["steps"],
            kind: "list",
            labelKey: "productSteps",
            maxItems: 8,
            item: [
              { path: ["title"], kind: "text", labelKey: "stepTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
            ],
          },
          {
            path: ["documents"],
            kind: "list",
            labelKey: "productDocuments",
            maxItems: 8,
            item: [
              { path: ["label"], kind: "text", labelKey: "documentLabel" },
              { path: ["href"], kind: "url", labelKey: "documentHref" },
              { path: ["note"], kind: "text", labelKey: "documentNote" },
            ],
          },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
          {
            path: ["secondaryAction", "label"],
            kind: "text",
            labelKey: "secondaryActionLabel",
          },
          {
            path: ["secondaryAction", "href"],
            kind: "url",
            labelKey: "secondaryActionHref",
          },
        ],
      },
    },
  ],
};
