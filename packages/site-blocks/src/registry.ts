import { createElement } from "react";

import Ajv2020, {
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";

import {
  InvalidBlockDataError,
  InvalidBlockManifestError,
  UnknownBlockTypeError,
  UnknownBlockVersionError,
  type BlockValidationIssue,
} from "./errors";
import type {
  BlockDefinition,
  BlockRegistry,
  JsonObject,
  SiteBlock,
  SiteBlockManifest,
} from "./types";

const BLOCK_TYPE_PATTERN = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/;

function validationDetails(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map(
    (error) => `${error.instancePath || "/"} ${error.message ?? "invalid"}`,
  );
}

/** Ajv reports a missing property on the parent object, so `required` errors
 *  carry the absent key in `params` rather than in `instancePath`. Appending it
 *  keeps every issue addressed to the field a form would render. */
function validationIssues(
  errors: ErrorObject[] | null | undefined,
): BlockValidationIssue[] {
  return (errors ?? []).map((error) => {
    const path = error.instancePath
      .split("/")
      .slice(1)
      .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
    if (error.keyword === "required") {
      const missing = (error.params as { missingProperty?: string })
        .missingProperty;
      if (missing !== undefined) path.push(missing);
    }
    return {
      path,
      message: error.message ?? "invalid",
      keyword: error.keyword,
    };
  });
}

function assertLinearVersions(definition: BlockDefinition): void {
  const versions = definition.schemas.map(({ version }) => version);
  const expected = Array.from(
    { length: definition.latestVersion },
    (_, index) => index + 1,
  );
  if (versions.some((version, index) => version !== expected[index])) {
    throw new InvalidBlockManifestError(
      `Schematy ${definition.type} muszą tworzyć linię od v1 do v${definition.latestVersion}.`,
    );
  }
  for (let version = 1; version < definition.latestVersion; version += 1) {
    if (definition.migrators[version] === undefined) {
      throw new InvalidBlockManifestError(
        `Brak migratora ${definition.type} v${version} -> v${version + 1}.`,
      );
    }
  }
}

export function defineSiteBlockManifest(
  manifest: SiteBlockManifest,
): SiteBlockManifest {
  if (!/^[a-z][a-z0-9_]*$/.test(manifest.namespace)) {
    throw new InvalidBlockManifestError(
      `Nieprawidłowy namespace: ${manifest.namespace}`,
    );
  }
  for (const definition of manifest.blocks) {
    if (
      !BLOCK_TYPE_PATTERN.test(definition.type) ||
      !definition.type.startsWith(`${manifest.namespace}.`)
    ) {
      throw new InvalidBlockManifestError(
        `Typ ${definition.type} nie należy do namespace ${manifest.namespace}.`,
      );
    }
    assertLinearVersions(definition);
  }
  return manifest;
}

export function createSiteBlockRegistry(
  manifests: readonly SiteBlockManifest[],
): BlockRegistry {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  const definitions = new Map<string, BlockDefinition>();
  const validators = new Map<string, Map<number, ValidateFunction>>();

  for (const candidate of manifests) {
    const manifest = defineSiteBlockManifest(candidate);
    for (const definition of manifest.blocks) {
      if (definitions.has(definition.type)) {
        throw new InvalidBlockManifestError(
          `Typ bloku ${definition.type} został zarejestrowany więcej niż raz.`,
        );
      }
      definitions.set(definition.type, definition);
      validators.set(
        definition.type,
        new Map(
          definition.schemas.map(({ version, schema }) => [
            version,
            ajv.compile(schema),
          ]),
        ),
      );
    }
  }

  function definitionFor(blockType: string): BlockDefinition {
    const definition = definitions.get(blockType);
    if (definition === undefined) {
      throw new UnknownBlockTypeError(blockType);
    }
    return definition;
  }

  function validate(block: SiteBlock): void {
    definitionFor(block.block_type);
    const validator = validators
      .get(block.block_type)
      ?.get(block.schema_version);
    if (validator === undefined) {
      throw new UnknownBlockVersionError(
        block.block_type,
        block.schema_version,
      );
    }
    if (!validator(block.data)) {
      throw new InvalidBlockDataError(
        block.block_type,
        block.schema_version,
        validationDetails(validator.errors),
        validationIssues(validator.errors),
      );
    }
  }

  function migrate(block: SiteBlock): SiteBlock {
    validate(block);
    const definition = definitionFor(block.block_type);
    let version = block.schema_version;
    let data: JsonObject = structuredClone(block.data);
    while (version < definition.latestVersion) {
      const migrator = definition.migrators[version];
      if (migrator === undefined) {
        throw new UnknownBlockVersionError(block.block_type, version);
      }
      data = migrator(data);
      version += 1;
      validate({ block_type: block.block_type, schema_version: version, data });
    }
    return { block_type: block.block_type, schema_version: version, data };
  }

  return {
    definitions,
    validate,
    migrate,
    render(block, key) {
      const migrated = migrate(block);
      const definition = definitionFor(migrated.block_type);
      return createElement(definition.component, { data: migrated.data, key });
    },
  };
}
