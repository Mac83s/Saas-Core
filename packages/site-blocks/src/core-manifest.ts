import { createElement } from "react";

import contactV1Schema from "@saas-core/contracts/site-blocks/core.contact.v1.schema.json";
import faqV1Schema from "@saas-core/contracts/site-blocks/core.faq.v1.schema.json";
import featureListV1Schema from "@saas-core/contracts/site-blocks/core.feature_list.v1.schema.json";
import heroV1Schema from "@saas-core/contracts/site-blocks/core.hero.v1.schema.json";
import heroV2Schema from "@saas-core/contracts/site-blocks/core.hero.v2.schema.json";
import richTextV1Schema from "@saas-core/contracts/site-blocks/core.rich_text.v1.schema.json";

import type {
  ContactV1Data,
  FaqV1Data,
  FeatureListV1Data,
  HeroV1Data,
  HeroV2Data,
  JsonObject,
  RichTextV1Data,
  SiteBlockManifest,
} from "./types";

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
            rel: action.href.startsWith("https://") ? "noreferrer" : undefined,
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
  ],
};
