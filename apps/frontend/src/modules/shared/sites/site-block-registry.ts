/** The block types of this deployment: the core's own and those of the
 *  modules its profile composes (ADR-077). One registry and one library for
 *  the studio and for the published page — a type the page may carry is a
 *  type the editor knows, and a module the profile does not name brings
 *  neither (docs/architecture/site-block-types.md).
 *
 *  No `"use client"`: the public renderer reads this on the server. */

import {
  composedModuleBlocks,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  offeredSectionTemplates,
} from "@saas-core/site-blocks";

import { deployment } from "../../../generated/deployment";
import { siteBlocks } from "../../../product/site-blocks";

const composed = composedModuleBlocks(siteBlocks, deployment.modules);

export const registry = createSiteBlockRegistry([
  coreSiteBlockManifest,
  ...composed.map((set) => set.manifest),
]);

/** What the library and the layout switch offer: the core's sections, then
 *  each composed module's. */
export const sectionTemplates = [
  ...offeredSectionTemplates(),
  ...composed.flatMap((set) => set.sectionTemplates),
];

/** The composed modules that bring blocks: what their sections require. */
export const blockModules = composed.map((set) => set.manifest.moduleId);
