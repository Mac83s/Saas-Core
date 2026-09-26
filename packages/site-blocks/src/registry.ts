import {
  cloneElement,
  createElement,
  type FunctionComponent,
  type ReactElement,
} from "react";
import decorationSchema from "@saas-core/contracts/site-blocks/section-decoration.v1.schema.json";
import presentationSchema from "@saas-core/contracts/site-blocks/section-presentation.v1.schema.json";
import presentationV2Schema from "@saas-core/contracts/site-blocks/section-presentation.v2.schema.json";
import { decorateSection } from "./section-decoration-renderer";

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
  BlockComponentProps,
  BlockDefinition,
  BlockFieldDefinition,
  BlockRegistry,
  JsonObject,
  SectionPresentationV1,
  SectionPresentationV2,
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

/** A node array whose items are a `oneOf` of node shapes (rich text v2):
 *  with `allErrors`, Ajv reports the failures of every branch, so an invalid
 *  paragraph also "misses" a heading's level and a figure's image. Only the
 *  branch the node's own `type` names speaks for it, so its errors are taken
 *  from validating the node against that branch alone. A node of no known
 *  type keeps just the `oneOf` error. Ajv's `schemaPath` cannot tell branches
 *  apart (a `$ref` compiled once reports paths relative to its own schema),
 *  hence the re-validation. Needs the validator's Ajv to run with `verbose`. */
function ownBranchErrors(
  ajv: Ajv2020,
  rootId: string | undefined,
  errors: readonly ErrorObject[],
): ErrorObject[] {
  let result = [...errors];
  for (const union of errors) {
    if (
      union.keyword !== "oneOf" ||
      !Array.isArray(union.schema) ||
      !result.includes(union)
    )
      continue;
    const at = union.instancePath;
    const branches = (union.schema as { $ref?: string }[]).map((candidate) =>
      typeof candidate.$ref === "string"
        ? ajv.getSchema(
            candidate.$ref.startsWith("#")
              ? `${rootId ?? ""}${candidate.$ref}`
              : candidate.$ref,
          )
        : ajv.compile(candidate),
    );
    const typeOf = (validator: ValidateFunction | undefined) =>
      (validator?.schema as SchemaNode | undefined)?.properties?.type?.const;
    // Only a union discriminated by `type` is narrowed; any other stays as is.
    if (branches.some((validator) => typeof typeOf(validator) !== "string"))
      continue;
    const type = (union.data as { type?: unknown } | null)?.type;
    const branch = branches.find((validator) => typeOf(validator) === type);
    const own =
      branch !== undefined && !branch(union.data)
        ? ownBranchErrors(ajv, rootId, branch.errors ?? []).map((error) => ({
            ...error,
            instancePath: `${at}${error.instancePath}`,
          }))
        : [];
    result = result.filter(
      (error) =>
        (error.instancePath !== at &&
          !error.instancePath.startsWith(`${at}/`)) ||
        (own.length === 0 && error === union),
    );
    result.push(...own);
  }
  return result;
}

/** Classes only for the values that are set; an empty envelope adds nothing,
 *  so legacy markup stays byte-identical. */
function presentationClassName(
  presentation: SectionPresentationV1 | SectionPresentationV2 | undefined,
): string {
  if (!presentation || (!presentation.inner && !presentation.surface))
    return "";
  return [
    "site-presentation",
    presentation.inner ? `site-presentation--inner-${presentation.inner}` : "",
    presentation.surface
      ? `site-presentation--surface-${presentation.surface}`
      : "",
  ]
    .filter(Boolean)
    .join(" ");
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

type SchemaNode = {
  type?: string;
  const?: unknown;
  enum?: readonly unknown[];
  properties?: Record<string, SchemaNode>;
  items?: SchemaNode;
};

/** Walks a field path through the block's latest JSON Schema. A path that does
 *  not resolve means the editor would render an input bound to a property the
 *  contract does not have — caught here rather than as a save-time rejection. */
function assertFieldPath(
  definition: BlockDefinition,
  field: BlockFieldDefinition,
  schema: SchemaNode,
): void {
  if (field.path.length === 0) {
    throw new InvalidBlockManifestError(
      `Pole katalogu ${definition.type} musi mieć niepustą ścieżkę.`,
    );
  }
  let node: SchemaNode | undefined = schema;
  for (const segment of field.path) {
    node = node?.properties?.[segment];
    if (node === undefined) {
      throw new InvalidBlockManifestError(
        `Ścieżka ${field.path.join(".")} nie istnieje w schemacie ${definition.type} v${definition.latestVersion}.`,
      );
    }
  }
  if (field.kind === "list") {
    if (field.item === undefined || field.item.length === 0) {
      throw new InvalidBlockManifestError(
        `Pole listy ${field.path.join(".")} w ${definition.type} musi opisywać kształt wpisu.`,
      );
    }
    const itemSchema = node.items;
    if (itemSchema === undefined) {
      throw new InvalidBlockManifestError(
        `Ścieżka ${field.path.join(".")} w ${definition.type} nie jest tablicą w schemacie.`,
      );
    }
    for (const entry of field.item) {
      assertFieldPath(definition, entry, itemSchema);
    }
  } else if (field.kind === "richText" && node.type !== "array") {
    // The writing panel edits the whole node array; its union of node shapes
    // is the schema's business, not the catalogue's.
    throw new InvalidBlockManifestError(
      `Pole ${field.path.join(".")} w ${definition.type} nie jest tablicą węzłów.`,
    );
  } else if (
    field.kind === "choice" &&
    JSON.stringify(
      field.options?.[0] === "" ? field.options.slice(1) : field.options,
    ) !== JSON.stringify(node.enum)
  ) {
    // The select offers exactly what the contract allows, in its order (the
    // first is what absent means). A leading "" offers absence itself, for a
    // value that is optional rather than one of the enum's.
    throw new InvalidBlockManifestError(
      `Opcje pola ${field.path.join(".")} w ${definition.type} różnią się od schematu.`,
    );
  } else if (field.item !== undefined) {
    throw new InvalidBlockManifestError(
      `Pole ${field.path.join(".")} w ${definition.type} opisuje wpisy, ale nie jest listą.`,
    );
  }
}

function assertCatalog(definition: BlockDefinition): void {
  const catalog = definition.catalog;
  if (catalog === undefined) return;
  const latest = definition.schemas.find(
    ({ version }) => version === definition.latestVersion,
  );
  if (latest === undefined) {
    throw new InvalidBlockManifestError(
      `Brak schematu ${definition.type} v${definition.latestVersion}.`,
    );
  }
  for (const field of catalog.fields) {
    assertFieldPath(definition, field, latest.schema as SchemaNode);
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
    assertCatalog(definition);
  }
  return manifest;
}

export function createSiteBlockRegistry(
  manifests: readonly SiteBlockManifest[],
): BlockRegistry {
  // `verbose` gives union errors their branches and data (ownBranchErrors).
  const ajv = new Ajv2020({ allErrors: true, strict: true, verbose: true });
  const validateDecoration = ajv.compile(decorationSchema);
  const presentationValidators = {
    1: ajv.compile(presentationSchema),
    2: ajv.compile(presentationV2Schema),
  };
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
    if (
      block.decoration !== undefined &&
      !validateDecoration(block.decoration)
    ) {
      throw new InvalidBlockDataError(
        block.block_type,
        block.schema_version,
        validationDetails(validateDecoration.errors),
        validationIssues(validateDecoration.errors).map((issue) => ({
          ...issue,
          scope: "decoration" as const,
        })),
      );
    }
    // Checked against the version it names; any other version fails v1.
    const validatePresentation =
      block.presentation?.schemaVersion === 2
        ? presentationValidators[2]
        : presentationValidators[1];
    if (
      block.presentation !== undefined &&
      !validatePresentation(block.presentation)
    ) {
      throw new InvalidBlockDataError(
        block.block_type,
        block.schema_version,
        validationDetails(validatePresentation.errors),
        validationIssues(validatePresentation.errors).map((issue) => ({
          ...issue,
          scope: "presentation" as const,
        })),
      );
    }
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
      const errors = ownBranchErrors(
        ajv,
        (validator.schema as { $id?: string }).$id,
        validator.errors ?? [],
      );
      throw new InvalidBlockDataError(
        block.block_type,
        block.schema_version,
        validationDetails(errors),
        validationIssues(errors),
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
    return {
      block_type: block.block_type,
      schema_version: version,
      data,
      ...(block.decoration
        ? { decoration: structuredClone(block.decoration) }
        : {}),
      ...(block.presentation
        ? { presentation: structuredClone(block.presentation) }
        : {}),
    };
  }

  return {
    definitions,
    validate,
    migrate,
    render(block, key, editor, imageRenderer, formRenderer, options) {
      const migrated = migrate(block);
      const definition = definitionFor(migrated.block_type);
      const effective = {
        ...options,
        preview: editor ? true : (options?.preview ?? true),
      };
      const props: BlockComponentProps = {
        data: migrated.data,
        options: effective,
        ...(editor ? { editor } : {}),
        ...(imageRenderer ? { imageRenderer } : {}),
        ...(formRenderer ? { formRenderer } : {}),
      };
      const decorated = decorateSection(
        createElement(definition.component, { ...props, key }),
        migrated.decoration,
        effective,
        key,
      );
      const presentation = presentationClassName(migrated.presentation);
      // The section anchor is a publication id, like heading ids: a preview
      // sits inside the panel, where it could collide with the panel's own.
      const anchor =
        effective.preview === false &&
        migrated.presentation?.schemaVersion === 2
          ? migrated.presentation.anchor
          : undefined;
      if (!presentation && !anchor) return decorated;
      // No wrapper of its own: classes and id join the outermost element —
      // the decoration layer when there is one, else the block's own root.
      // Block components are plain functions without hooks, so calling one
      // here yields exactly the element React would have rendered. A block
      // that delegates to another component (contact v2 layouts) is followed
      // down to the HTML element, or the classes would land on a prop the
      // inner component never reads.
      let root = decorated as ReactElement<{ className?: string; id?: string }>;
      while (typeof root.type === "function")
        root = (root.type as FunctionComponent<typeof root.props>)(
          root.props,
        ) as typeof root;
      return cloneElement(root, {
        key,
        ...(presentation
          ? {
              className: [root.props.className, presentation]
                .filter(Boolean)
                .join(" "),
            }
          : {}),
        ...(anchor ? { id: anchor } : {}),
      });
    },
  };
}
