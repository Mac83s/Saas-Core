/** The block types the product's own slot brings (ADR-077). Core's slot is
 *  empty, so here this only proves the checks themselves on the test-only
 *  vertical; in a product repository the same file runs over the product's
 *  sets — a missing message or a seed its schema refuses fails the product's
 *  gate instead of a customer's studio. */

import { render } from "@testing-library/react";
import axe from "axe-core";
import { expect, test } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderDraftPreview,
  sectionTemplateBlock,
} from "@saas-core/site-blocks";

import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { mergeMessages } from "../../../i18n/merge-messages";
import { product } from "../../../product";
import { siteBlocks } from "../../../product/site-blocks";
import { moduleBlockProblems } from "./module-block-checks";
import {
  sampleModuleBlocks,
  sampleModuleMessages,
} from "./testing/sample-module-blocks";

const sitesOf = (messages: Record<string, unknown>, extra: object = {}) =>
  mergeMessages(messages, extra as Record<string, unknown>).Sites as Record<
    string,
    unknown
  >;
// jsdom draws nothing: contrast is checked in a browser.
const quiet = { rules: { "color-contrast": { enabled: false } } };
const tokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

test("every set of the product's slot can be shown by the studio", async () => {
  const sites = {
    pl: sitesOf(pl, product.messages?.pl),
    en: sitesOf(en, product.messages?.en),
  };
  for (const set of siteBlocks) {
    expect(moduleBlockProblems(set, sites), set.manifest.moduleId).toEqual([]);
    // Each section, as the library previews it, is accessible markup.
    const registry = createSiteBlockRegistry([
      coreSiteBlockManifest,
      set.manifest,
    ]);
    for (const section of set.sectionTemplates) {
      const { container, unmount } = render(
        renderDraftPreview(
          {
            kind: "draft-preview",
            versionId: section.id,
            blocks: [sectionTemplateBlock(section, "pl", registry)],
            designTokens: tokens,
          },
          registry,
        ),
      );
      expect((await axe.run(container, quiet)).violations, section.id).toEqual(
        [],
      );
      unmount();
    }
  }
});

test("the checks pass the sample vertical and name what a set lacks", () => {
  const complete = {
    pl: sitesOf(pl, sampleModuleMessages.pl),
    en: sitesOf(en, sampleModuleMessages.en),
  };
  expect(moduleBlockProblems(sampleModuleBlocks, complete)).toEqual([]);

  // The product forgot the English words of one field and of one option.
  const english = structuredClone(sampleModuleMessages.en.Sites) as Record<
    string,
    unknown
  >;
  delete english.sampleIntro;
  delete (english.sampleOrderOptions as Record<string, unknown>).newest;
  expect(
    moduleBlockProblems(sampleModuleBlocks, {
      ...complete,
      en: sitesOf(en, { Sites: english }),
    }),
  ).toEqual([
    "vertical.sample.record_list: brak tekstu Sites.sampleIntro (en)",
    "vertical.sample.record_list: brak tekstu Sites.sampleOrderOptions.newest (en)",
  ]);

  // A seed its schema refuses never reaches a page.
  const broken = {
    ...sampleModuleBlocks,
    sectionTemplates: sampleModuleBlocks.sectionTemplates.map((section) => ({
      ...section,
      seed: { ...section.seed, en: { intro: "No heading" } },
    })),
  };
  expect(moduleBlockProblems(broken, complete)).toEqual([
    expect.stringContaining(
      "vertical.sample.record_list_classic: zalążek (en) nie spełnia schematu",
    ),
  ]);
});
