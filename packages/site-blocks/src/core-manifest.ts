import { createElement } from "react";

import contactV1Schema from "@saas-core/contracts/site-blocks/core.contact.v1.schema.json";
import entryListV1Schema from "@saas-core/contracts/site-blocks/core.entry_list.v1.schema.json";
import bookingV1Schema from "@saas-core/contracts/site-blocks/core.booking.v1.schema.json";
import faqV1Schema from "@saas-core/contracts/site-blocks/core.faq.v1.schema.json";
import featureListV1Schema from "@saas-core/contracts/site-blocks/core.feature_list.v1.schema.json";
import footerV1Schema from "@saas-core/contracts/site-blocks/core.footer.v1.schema.json";
import heroV1Schema from "@saas-core/contracts/site-blocks/core.hero.v1.schema.json";
import heroV2Schema from "@saas-core/contracts/site-blocks/core.hero.v2.schema.json";
import pricingV1Schema from "@saas-core/contracts/site-blocks/core.pricing.v1.schema.json";
import richTextV1Schema from "@saas-core/contracts/site-blocks/core.rich_text.v1.schema.json";
import testimonialsV1Schema from "@saas-core/contracts/site-blocks/core.testimonials.v1.schema.json";

import type {
  BookingV1Data,
  ContactV1Data,
  EntryListV1Data,
  FaqV1Data,
  FeatureListV1Data,
  FooterV1Data,
  HeroV1Data,
  HeroV2Data,
  JsonObject,
  PricingV1Data,
  RichTextV1Data,
  SiteBlockManifest,
  TestimonialsV1Data,
} from "./types";

function externalRel(href: string): "noreferrer" | undefined {
  return href.startsWith("https://") ? "noreferrer" : undefined;
}

function HeroBlock({ data }: { data: JsonObject }) {
  const hero = data as HeroV2Data;
  const action = hero.action;
  return createElement(
    "section",
    {
      className: "site-block site-block--hero",
      "data-block-type": "core.hero",
    },
    createElement("h1", null, hero.title),
    hero.text ? createElement("p", null, hero.text) : null,
    action
      ? createElement(
          "a",
          {
            href: action.href,
            rel: externalRel(action.href),
          },
          action.label,
        )
      : null,
  );
}

function RichTextBlock({ data }: { data: JsonObject }) {
  const richText = data as RichTextV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--rich-text",
      "data-block-type": "core.rich_text",
    },
    createElement("p", null, richText.text),
  );
}

function FeatureListBlock({ data }: { data: JsonObject }) {
  const featureList = data as FeatureListV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--feature-list",
      "data-block-type": "core.feature_list",
    },
    featureList.title ? createElement("h2", null, featureList.title) : null,
    createElement(
      "ul",
      null,
      featureList.items.map((item, index) =>
        createElement(
          "li",
          { key: index },
          createElement("h3", null, item.title),
          item.text ? createElement("p", null, item.text) : null,
        ),
      ),
    ),
  );
}

function FaqBlock({ data }: { data: JsonObject }) {
  const faq = data as FaqV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--faq",
      "data-block-type": "core.faq",
    },
    faq.title ? createElement("h2", null, faq.title) : null,
    createElement(
      "dl",
      null,
      faq.items.flatMap((item, index) => [
        createElement("dt", { key: `q-${index}` }, item.question),
        createElement("dd", { key: `a-${index}` }, item.answer),
      ]),
    ),
  );
}

function ContactBlock({ data }: { data: JsonObject }) {
  const contact = data as ContactV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--contact",
      "data-block-type": "core.contact",
    },
    contact.title ? createElement("h2", null, contact.title) : null,
    createElement(
      "address",
      null,
      contact.email
        ? createElement("a", { href: `mailto:${contact.email}` }, contact.email)
        : null,
      contact.phone
        ? createElement(
            "a",
            { href: `tel:${contact.phone.replace(/[^0-9+]/g, "")}` },
            contact.phone,
          )
        : null,
      contact.address ? createElement("p", null, contact.address) : null,
    ),
  );
}

function TestimonialsBlock({ data }: { data: JsonObject }) {
  const testimonials = data as TestimonialsV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--testimonials",
      "data-block-type": "core.testimonials",
    },
    testimonials.title ? createElement("h2", null, testimonials.title) : null,
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
            createElement("p", null, item.quote),
            createElement(
              "footer",
              null,
              createElement("cite", null, item.author),
              item.role ? createElement("span", null, item.role) : null,
            ),
          ),
        ),
      ),
    ),
  );
}

function PricingBlock({ data }: { data: JsonObject }) {
  const pricing = data as PricingV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--pricing",
      "data-block-type": "core.pricing",
    },
    pricing.title ? createElement("h2", null, pricing.title) : null,
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
            createElement("h3", null, item.name),
            createElement("p", { className: "site-block__price" }, item.price),
            item.description
              ? createElement("p", null, item.description)
              : null,
          ),
        ),
      ),
    ),
  );
}

function BookingBlock({ data }: { data: JsonObject }) {
  const booking = data as BookingV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--booking",
      "data-block-type": "core.booking",
    },
    createElement("h2", null, booking.title),
    booking.text ? createElement("p", null, booking.text) : null,
    createElement(
      "a",
      { href: booking.action.href, rel: externalRel(booking.action.href) },
      booking.action.label,
    ),
  );
}

function FooterBlock({ data }: { data: JsonObject }) {
  const footer = data as FooterV1Data;
  return createElement(
    "footer",
    {
      className: "site-block site-block--footer",
      "data-block-type": "core.footer",
    },
    createElement("p", null, footer.text),
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
                "a",
                { href: link.href, rel: externalRel(link.href) },
                link.label,
              ),
            ),
          ),
        ),
  );
}

/** The blog index, and any "latest posts" section an operator places by hand.
 *  The items are a projection of what is published (ADR-035 §7), so the block
 *  renders whatever it is handed rather than reaching for data itself. */
function EntryListBlock({ data }: { data: JsonObject }) {
  const list = data as EntryListV1Data;
  return createElement(
    "section",
    {
      className: "site-block site-block--entry-list",
      "data-block-type": "core.entry_list",
    },
    list.title === undefined ? null : createElement("h2", null, list.title),
    list.items.length === 0
      ? createElement("p", null, list.empty_text ?? "")
      : createElement(
          "ul",
          null,
          list.items.map((item, index) =>
            createElement(
              "li",
              { key: index },
              createElement(
                "a",
                { href: item.path },
                createElement("h3", null, item.title),
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
                : createElement("p", null, item.excerpt),
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

export const coreSiteBlockManifest: SiteBlockManifest = {
  moduleId: "shared.sites",
  namespace: "core",
  blocks: [
    {
      type: "core.hero",
      latestVersion: 2,
      schemas: [
        { version: 1, schema: heroV1Schema },
        { version: 2, schema: heroV2Schema },
      ],
      migrators: { 1: migrateHeroV1ToV2 },
      component: HeroBlock,
      catalog: {
        category: "start",
        labelKey: "heroBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["text"], kind: "textarea", labelKey: "text" },
          { path: ["action", "label"], kind: "text", labelKey: "actionLabel" },
          { path: ["action", "href"], kind: "url", labelKey: "actionHref" },
        ],
      },
    },
    {
      type: "core.rich_text",
      latestVersion: 1,
      schemas: [{ version: 1, schema: richTextV1Schema }],
      migrators: {},
      component: RichTextBlock,
      catalog: {
        category: "about",
        labelKey: "richTextBlock",
        fields: [{ path: ["text"], kind: "textarea", labelKey: "text" }],
      },
    },
    {
      type: "core.feature_list",
      latestVersion: 1,
      schemas: [{ version: 1, schema: featureListV1Schema }],
      migrators: {},
      component: FeatureListBlock,
      catalog: {
        category: "offer",
        labelKey: "featureListBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          {
            path: ["items"],
            kind: "list",
            labelKey: "featureItems",
            item: [
              { path: ["title"], kind: "text", labelKey: "featureTitle" },
              { path: ["text"], kind: "textarea", labelKey: "text" },
            ],
          },
        ],
      },
    },
    {
      type: "core.faq",
      latestVersion: 1,
      schemas: [{ version: 1, schema: faqV1Schema }],
      migrators: {},
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
      latestVersion: 1,
      schemas: [{ version: 1, schema: contactV1Schema }],
      migrators: {},
      component: ContactBlock,
      catalog: {
        category: "contact",
        labelKey: "contactBlock",
        fields: [
          { path: ["title"], kind: "text", labelKey: "heading" },
          { path: ["email"], kind: "text", labelKey: "contactEmail" },
          { path: ["phone"], kind: "text", labelKey: "contactPhone" },
          { path: ["address"], kind: "textarea", labelKey: "contactAddress" },
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
      latestVersion: 1,
      schemas: [{ version: 1, schema: footerV1Schema }],
      migrators: {},
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
            ],
          },
        ],
      },
    },
  ],
};
