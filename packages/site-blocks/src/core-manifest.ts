import { createElement } from "react";

import heroV1Schema from "@saas-core/contracts/site-blocks/core.hero.v1.schema.json";
import heroV2Schema from "@saas-core/contracts/site-blocks/core.hero.v2.schema.json";
import richTextV1Schema from "@saas-core/contracts/site-blocks/core.rich_text.v1.schema.json";

import type {
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
    },
    {
      type: "core.rich_text",
      latestVersion: 1,
      schemas: [{ version: 1, schema: richTextV1Schema }],
      migrators: {},
      component: RichTextBlock,
    },
  ],
};
