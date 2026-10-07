/** Block types a shared or vertical module brings (ADR-077,
 *  docs/architecture/site-block-types.md).
 *
 *  The contract is the module's own directory of the block contracts,
 *  `modules/<module id>/`: a manifest, a schema per version. The backend
 *  reads it where the deployment composes the module; here the same manifest
 *  is joined with what only code can give — the component that draws the
 *  block and the studio's form — and checked against it, so the two halves
 *  cannot name different types or versions. */

import type { ComponentType } from "react";

import { InvalidBlockManifestError } from "./errors";
import { defineSiteBlockManifest } from "./registry";
import type { SectionTemplate } from "./section-templates";
import type {
  BlockCatalogEntry,
  BlockComponentProps,
  BlockMigrator,
  JsonObject,
  SiteBlockManifest,
} from "./types";

type PanelLocale = "pl" | "en";

/** A section of the studio's library, as the module's manifest gives it. */
export interface ModuleSection {
  readonly id: string;
  readonly version: number;
  readonly schemaVersion: number;
  readonly layout?: string;
  readonly labels: Record<
    PanelLocale,
    { name: string; description: string; usage: string }
  >;
  readonly seed: Record<PanelLocale, object>;
}

/** `modules/<module id>/manifest.json`, as imported. */
export interface ModuleBlockContract {
  readonly schemaVersion: number;
  readonly module: string;
  readonly blocks: readonly {
    readonly type: string;
    readonly latestVersion: number;
    readonly schemas: Readonly<Record<string, string>>;
    readonly serverBuilt?: boolean;
    readonly translation?: object;
    readonly sections?: readonly ModuleSection[];
  }[];
}

/** What code adds to one type of the contract. */
export interface ModuleBlockImplementation {
  /** The schema of every version, v1 first: the contract's own files,
   *  imported. Each is checked by its `$id` to be the file the manifest
   *  names. */
  readonly schemas: readonly object[];
  /** `migrators[n]` turns version n data into n + 1; one per added version. */
  readonly migrators?: Readonly<Record<number, BlockMigrator>>;
  /** A plain function without hooks whose root is an HTML element; whatever
   *  must run in the visitor's browser is a client component inside it. */
  readonly component: ComponentType<BlockComponentProps>;
  /** The block shows the module's live records: a published page draws it
   *  only with the answer of the module's public source (`props.live`). */
  readonly live?: true;
  /** The studio's form and the block's place among the kinds of section.
   *  Never on a block only the server builds. */
  readonly catalog?: BlockCatalogEntry;
}

/** One module's block types, ready for the product slot
 *  (`apps/frontend/src/product/site-blocks.ts`). */
export interface ModuleSiteBlocks {
  readonly manifest: SiteBlockManifest;
  /** The module's sections of the studio's library. */
  readonly sectionTemplates: readonly SectionTemplate[];
}

/** What every block type of a module starts with: its id and a dot, a hyphen
 *  of the id written as an underscore. */
export function moduleBlockPrefix(moduleId: string): string {
  return `${moduleId.replaceAll("-", "_")}.`;
}

function librarySection(
  moduleId: string,
  blockType: string,
  section: ModuleSection,
): SectionTemplate {
  return {
    id: section.id,
    version: section.version,
    blockType,
    schemaVersion: section.schemaVersion,
    // A block without layouts is its one `classic` section (the stay widget).
    layout: section.layout ?? "classic",
    kind: "default",
    industries: [],
    labels: section.labels,
    goals: [],
    composition: {
      role: "module",
      preferredPosition: "body",
      recommendedNext: [],
      repeatable: true,
    },
    // Offered only where the deployment composes the module.
    requirements: {
      requiredEntitlements: [],
      requiredModules: [moduleId],
      media: "none",
    },
    seed: section.seed as Record<PanelLocale, JsonObject>,
  };
}

export function defineModuleSiteBlocks(
  contract: ModuleBlockContract,
  implementations: Readonly<Record<string, ModuleBlockImplementation>>,
): ModuleSiteBlocks {
  const moduleId = contract.module;
  const prefix = moduleBlockPrefix(moduleId);
  const fail = (message: string): never => {
    throw new InvalidBlockManifestError(`Bloki modułu ${moduleId}: ${message}`);
  };
  const declared = new Set(contract.blocks.map((block) => block.type));
  for (const type of Object.keys(implementations))
    if (!declared.has(type)) fail(`typu ${type} nie ma w manifeście.`);

  const sectionTemplates: SectionTemplate[] = [];
  const blocks = contract.blocks.map((block) => {
    const implementation = implementations[block.type];
    if (implementation === undefined)
      return fail(`typ ${block.type} nie ma komponentu.`);
    if (!block.type.startsWith(prefix))
      fail(`typ ${block.type} nie nosi nazwy modułu (${prefix}…).`);
    if (implementation.schemas.length !== block.latestVersion)
      fail(
        `typ ${block.type} ma ${block.latestVersion} wersji w manifeście i ${implementation.schemas.length} schematów w kodzie.`,
      );
    implementation.schemas.forEach((schema, index) => {
      const file = block.schemas[String(index + 1)];
      const id = (schema as { $id?: unknown }).$id;
      if (typeof id !== "string" || !id.endsWith(`/${file}`))
        fail(
          `schemat ${block.type} v${index + 1} nie jest plikiem ${file} ($id).`,
        );
    });
    if (block.serverBuilt && implementation.catalog !== undefined)
      fail(`blok ${block.type} buduje serwer: nie ma formularza ani sekcji.`);
    for (const section of block.sections ?? []) {
      if (!section.id.startsWith(`${block.type}_`))
        fail(`sekcja ${section.id} nie nosi nazwy bloku ${block.type}.`);
      sectionTemplates.push(librarySection(moduleId, block.type, section));
    }
    return {
      type: block.type,
      latestVersion: block.latestVersion,
      schemas: implementation.schemas.map((schema, index) => ({
        version: index + 1,
        schema,
      })),
      migrators: implementation.migrators ?? {},
      component: implementation.component,
      ...(implementation.live ? { live: true as const } : {}),
      ...(implementation.catalog ? { catalog: implementation.catalog } : {}),
    };
  });
  return {
    manifest: defineSiteBlockManifest({
      moduleId,
      namespace: moduleId.split(".")[0],
      blocks,
    }),
    sectionTemplates,
  };
}

/** The sets of the modules a deployment composes, in the slot's order: a
 *  module the profile does not name brings nothing — its types are unknown to
 *  the registry, its sections are in no library. */
export function composedModuleBlocks(
  sets: readonly ModuleSiteBlocks[],
  modules: readonly string[],
): readonly ModuleSiteBlocks[] {
  return sets.filter((set) => modules.includes(set.manifest.moduleId));
}
