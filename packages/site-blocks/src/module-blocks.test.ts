import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import contract from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/manifest.json";
import listV1 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_list.v1.schema.json";
import listV2 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_list.v2.schema.json";
import profileV1 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_profile.v1.schema.json";

import { coreSiteBlockManifest } from "./core-manifest";
import { InvalidBlockManifestError, UnknownBlockTypeError } from "./errors";
import {
  composedModuleBlocks,
  defineModuleSiteBlocks,
  moduleBlockPrefix,
  type ModuleBlockContract,
  type ModuleBlockImplementation,
} from "./module-blocks";
import { createSiteBlockRegistry } from "./registry";
import {
  availableSectionTemplates,
  offeredSectionTemplates,
} from "./section-templates";
import type { BlockComponentProps } from "./types";

const LIST = "vertical.sample.record_list";
const PROFILE = "vertical.sample.record_profile";
const sample = contract as ModuleBlockContract;

const Section = ({ data }: BlockComponentProps) =>
  h("section", null, String(data.heading ?? data.name));

const list: ModuleBlockImplementation = {
  schemas: [listV1, listV2],
  migrators: { 1: (data) => ({ ...data }) },
  component: Section,
  live: true,
  catalog: {
    category: "offer",
    labelKey: "sampleRecordList",
    fields: [{ path: ["heading"], kind: "text", labelKey: "sampleHeading" }],
  },
};
const profile: ModuleBlockImplementation = {
  schemas: [profileV1],
  component: Section,
};
const define = (
  implementations: Record<string, ModuleBlockImplementation> = {
    [LIST]: list,
    [PROFILE]: profile,
  },
  manifest: ModuleBlockContract = sample,
) => defineModuleSiteBlocks(manifest, implementations);

describe("block types a module brings", () => {
  it("joins the contract's manifest with the module's code", () => {
    const set = define();

    expect(set.manifest.moduleId).toBe("vertical.sample");
    expect(set.manifest.blocks.map((block) => block.type)).toEqual([
      LIST,
      PROFILE,
    ]);
    const [placed, built] = set.manifest.blocks;
    expect(placed.latestVersion).toBe(2);
    expect(placed.live).toBe(true);
    expect(placed.catalog?.labelKey).toBe("sampleRecordList");
    // What only the server builds has no place in the library.
    expect(built.catalog).toBeUndefined();
    expect(set.sectionTemplates.map((section) => section.id)).toEqual([
      "vertical.sample.record_list_classic",
    ]);
    expect(set.sectionTemplates[0]).toMatchObject({
      blockType: LIST,
      schemaVersion: 2,
      layout: "classic",
      requirements: { requiredModules: ["vertical.sample"] },
    });
  });

  it("registers beside the core, migrates and renders like a core block", () => {
    const set = define();
    const registry = createSiteBlockRegistry([
      coreSiteBlockManifest,
      set.manifest,
    ]);

    // v1 data is read as v2: an added version only adds.
    expect(
      registry.migrate({
        block_type: LIST,
        schema_version: 1,
        data: { heading: "Rekordy", order: "newest" },
      }),
    ).toEqual({
      block_type: LIST,
      schema_version: 2,
      data: { heading: "Rekordy", order: "newest" },
    });
    expect(() =>
      registry.validate({
        block_type: LIST,
        schema_version: 2,
        data: { heading: "Rekordy", colour: "red" },
      }),
    ).toThrow();
    expect(
      renderToStaticMarkup(
        registry.render(
          { block_type: PROFILE, schema_version: 1, data: { name: "Rekord" } },
          "0",
        ),
      ),
    ).toBe("<section>Rekord</section>");
  });

  it("offers a module's sections only where the module is composed", () => {
    const set = define();
    const registry = createSiteBlockRegistry([
      coreSiteBlockManifest,
      set.manifest,
    ]);
    const library = [...offeredSectionTemplates(), ...set.sectionTemplates];
    const offered = (modules: string[]) =>
      availableSectionTemplates(
        registry,
        { entitlements: ["sites.enabled"], modules },
        library,
      ).filter((template) => template.blockType === LIST);

    expect(offered(["shared.sites", "vertical.sample"])).toHaveLength(1);
    expect(offered(["shared.sites"])).toHaveLength(0);
    // The default library is the core's alone.
    expect(
      availableSectionTemplates(registry, {
        entitlements: ["sites.enabled"],
        modules: ["shared.sites", "vertical.sample"],
      }).some((template) => template.blockType === LIST),
    ).toBe(false);
  });

  it("leaves out the set of a module the deployment does not compose", () => {
    const set = define();

    expect(composedModuleBlocks([set], ["shared.sites"])).toEqual([]);
    expect(
      composedModuleBlocks([set], ["shared.sites", "vertical.sample"]),
    ).toEqual([set]);
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    expect(() =>
      registry.validate({
        block_type: LIST,
        schema_version: 2,
        data: { heading: "Rekordy" },
      }),
    ).toThrow(UnknownBlockTypeError);
  });

  it("names a type after its module, hyphens as underscores", () => {
    expect(moduleBlockPrefix("vertical.sample")).toBe("vertical.sample.");
    expect(moduleBlockPrefix("shared.model-port")).toBe("shared.model_port.");
  });

  it.each([
    [
      "a type the manifest does not have",
      () =>
        define({ [LIST]: list, [PROFILE]: profile, "vertical.sample.x": list }),
    ],
    ["a type without a component", () => define({ [LIST]: list })],
    [
      "fewer schemas than versions",
      () =>
        define({ [LIST]: { ...list, schemas: [listV2] }, [PROFILE]: profile }),
    ],
    [
      "a schema that is not the manifest's file",
      () =>
        define({
          [LIST]: { ...list, schemas: [listV2, listV1] },
          [PROFILE]: profile,
        }),
    ],
    [
      "a form on a block only the server builds",
      () =>
        define({
          [LIST]: list,
          [PROFILE]: { ...profile, catalog: list.catalog },
        }),
    ],
    [
      "a missing migrator",
      () => define({ [LIST]: { ...list, migrators: {} }, [PROFILE]: profile }),
    ],
    [
      "a form field the schema does not have",
      () =>
        define({
          [LIST]: {
            ...list,
            catalog: {
              ...list.catalog!,
              fields: [{ path: ["title"], kind: "text", labelKey: "x" }],
            },
          },
          [PROFILE]: profile,
        }),
    ],
    [
      "a type that does not carry the module's id",
      () =>
        define(
          { [LIST]: list, [PROFILE]: profile },
          {
            ...sample,
            module: "vertical.other",
          },
        ),
    ],
    [
      "a section named after another block",
      () =>
        define(
          { [LIST]: list, [PROFILE]: profile },
          {
            ...sample,
            blocks: [
              {
                ...sample.blocks[0],
                sections: [
                  {
                    ...sample.blocks[0].sections![0],
                    id: `${PROFILE}_classic`,
                  },
                ],
              },
              sample.blocks[1],
            ],
          },
        ),
    ],
  ])("refuses %s", (_what, build) => {
    expect(build).toThrow(InvalidBlockManifestError);
  });
});
