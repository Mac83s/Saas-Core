"use client";

/** The block editing machinery, shared by every surface that stores blocks.
 *
 *  Pages and collection entries hold the same `blocks` array under different
 *  endpoints (ADR-035 §7). Keeping one implementation here is what makes the
 *  panel, the future drag-and-drop canvas and the AI generator agree on what a
 *  block is — a second copy would drift the moment a block gains a field. */

import { useLocale, useTranslations } from "next-intl";

import { SectionDecorationFields } from "./section-decoration-fields";
import { ImageCropUpload } from "../media/crop";
import {
  useFieldArray,
  useWatch,
  type FieldValues,
  type Path,
  type UseFormReturn,
} from "react-hook-form";
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { z } from "zod";

import {
  coreSiteBlockManifest,
  coreSectionTemplates,
  createSiteBlockRegistry,
  InvalidBlockDataError,
  type BlockFieldDefinition,
  type JsonObject,
  type JsonValue,
  type SiteBlock,
  type SectionDecorationV1,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import type { MediaAsset } from "@saas-core/api-client";

export const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

export type BlockFormValues = {
  block_type: string;
  data: JsonObject;
  decoration?: SectionDecorationV1;
};

/** Every block the library offers, in manifest order. A block without a
 *  `catalog` entry still renders published pages but is not offered here. */
export const blockOptions = [...registry.definitions.values()].flatMap(
  (definition) =>
    definition.catalog === undefined
      ? []
      : [
          {
            type: definition.type,
            labelKey: definition.catalog.labelKey,
            category: definition.catalog.category,
            fields: definition.catalog.fields,
            latestVersion: definition.latestVersion,
          },
        ],
);

export type BlockOption = (typeof blockOptions)[number];

export function blockOption(blockType: string): BlockOption | undefined {
  return blockOptions.find((option) => option.type === blockType);
}

const MESSAGE_BY_KEYWORD: Record<string, string> = {
  required: "required",
  minLength: "required",
  maxLength: "tooLong",
  minItems: "required",
  maxItems: "tooMany",
  pattern: "invalidFormat",
};

function readAt(data: JsonObject, path: readonly string[]): JsonValue {
  let current: JsonValue = data;
  for (const segment of path) {
    if (!isObject(current)) return undefined as unknown as JsonValue;
    current = current[segment];
  }
  return current;
}

/** Empty strings are how a cleared input arrives from the DOM, but the contract
 *  has no notion of "present but blank": a hero with `text: ""` fails minLength
 *  where an absent `text` is simply optional. Dropping them here is what makes
 *  clearing an optional field mean removing it. */
function pruneEmpty(value: JsonValue): JsonValue | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  }
  if (Array.isArray(value)) {
    const items = value
      .map(pruneEmpty)
      .filter((item): item is JsonValue => item !== undefined);
    return items.length === 0 ? undefined : items;
  }
  if (isObject(value)) {
    const entries = Object.entries(value).flatMap(([key, nested]) => {
      const pruned = pruneEmpty(nested);
      return pruned === undefined ? [] : [[key, pruned] as const];
    });
    return entries.length === 0 ? undefined : Object.fromEntries(entries);
  }
  return value ?? undefined;
}

/** Field limits and formats live in the canonical JSON Schema (ADR-027). The
 *  form validates by asking the registry rather than restating them here: a
 *  second copy drifts, and the drift is only discovered when the backend
 *  rejects a draft the panel had already accepted. */
function refineAgainstBlockContract(
  block: BlockFormValues,
  context: z.RefinementCtx,
): void {
  const option = blockOption(block.block_type);
  if (option === undefined) return;
  try {
    registry.validate(toSiteBlock(blockPayload(block)));
  } catch (error) {
    if (!(error instanceof InvalidBlockDataError)) throw error;
    for (const issue of error.issues) {
      context.addIssue({
        code: "custom",
        path: [
          issue.scope === "decoration" ? "decoration" : "data",
          ...issue.path,
        ],
        message: MESSAGE_BY_KEYWORD[issue.keyword] ?? "invalid",
      });
    }
  }
  // Not expressible per-property: an optional nested object is valid when it is
  // absent, so half of a pair survives only because pruning removes it. The
  // editor has to catch that before it silently disappears on save.
  for (const field of option.fields) {
    if (field.path.length < 2) continue;
    const parent = field.path.slice(0, -1);
    const siblings = option.fields.filter(
      (candidate) =>
        candidate.path.length === field.path.length &&
        candidate.path.slice(0, -1).join("/") === parent.join("/"),
    );
    const filled = siblings.filter(
      (candidate) =>
        pruneEmpty(readAt(block.data, candidate.path)) !== undefined,
    );
    if (filled.length > 0 && filled.length < siblings.length) {
      for (const missing of siblings.filter(
        (candidate) => !filled.includes(candidate),
      )) {
        context.addIssue({
          code: "custom",
          path: ["data", ...missing.path],
          message: "required",
        });
      }
    }
  }
}

export const blockFormSchema = z
  .object({
    block_type: z.string(),
    // The shape is whatever the block's own JSON Schema says, so Zod only
    // asserts "an object" here; `refineAgainstBlockContract` is what actually
    // validates it, against the canonical contract.
    data: z.custom<JsonObject>((value) => isObject(value as JsonValue)),
    // The shared JSON Schema is checked by the same registry as the public renderer.
    decoration: z.custom<SectionDecorationV1>().optional(),
  })
  .superRefine((block, context) => {
    refineAgainstBlockContract(block, context);
  });

/** The shared components address fields by dot path and therefore work for any
 *  form whose values carry a `blocks` array, whatever else it carries. */
export function BlockFields<TValues extends FieldValues>({
  assets = [],
  form,
  index,
  isFirst,
  isLast,
  moveDown,
  moveUp,
  onRemove,
  type,
}: {
  assets?: readonly MediaAsset[];
  form: UseFormReturn<TValues>;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  moveDown: () => void;
  moveUp: () => void;
  onRemove: () => void;
  type: string;
}) {
  const t = useTranslations("Sites");
  const prefix = `blocks.${index}` as const;
  const option = blockOption(type);
  const decoration = useWatch({
    control: form.control,
    name: `${prefix}.decoration` as Path<TValues>,
  }) as SectionDecorationV1 | undefined;
  const locale = useLocale() === "en" ? "en" : "pl";
  const layouts = coreSectionTemplates().filter(
    (template) => template.blockType === type,
  );
  const layoutPath = `${prefix}.data.layout` as Path<TValues>;
  const selectedLayout =
    useWatch({ control: form.control, name: layoutPath }) ??
    layouts[0]?.layout ??
    "classic";
  const selectedTemplate = layouts.find(
    (template) => template.layout === selectedLayout,
  );
  return (
    <fieldset className="space-y-4 rounded-lg border p-4">
      <legend className="px-1 font-medium">
        {option ? t(option.labelKey) : type}
      </legend>
      <div className="flex justify-end gap-1">
        <Button
          aria-label={t("moveBlockUp")}
          disabled={isFirst}
          onClick={moveUp}
          size="icon"
          type="button"
          variant="ghost"
        >
          <ArrowUpIcon aria-hidden="true" />
        </Button>
        <Button
          aria-label={t("moveBlockDown")}
          disabled={isLast}
          onClick={moveDown}
          size="icon"
          type="button"
          variant="ghost"
        >
          <ArrowDownIcon aria-hidden="true" />
        </Button>
        <Button
          aria-label={t("removeBlock")}
          onClick={onRemove}
          size="icon"
          type="button"
          variant="ghost"
        >
          <Trash2Icon aria-hidden="true" />
        </Button>
      </div>
      {layouts.length > 0 && (
        <Field>
          <FieldLabel htmlFor={`block-layout-${index}`}>
            {t("sectionLibrary.layout")}
          </FieldLabel>
          <NativeSelect
            id={`block-layout-${index}`}
            {...form.register(layoutPath)}
            value={String(selectedLayout)}
          >
            {layouts.map((template) => (
              <option key={template.id} value={template.layout}>
                {template.labels[locale].name}
              </option>
            ))}
          </NativeSelect>
          {selectedTemplate && (
            <p className="text-sm text-muted-foreground">
              {selectedTemplate.labels[locale].description}{" "}
              {t("sectionLibrary.preservesContent")}
            </p>
          )}
        </Field>
      )}
      {type === "core.separator" && (
        <FieldGroup>
          {(
            [
              ["size", ["small", "medium", "large"], "medium"],
              ["width", ["full", "content", "short"], "content"],
              ["tone", ["muted", "accent"], "muted"],
            ] as const
          ).map(([field, choices, fallback]) => (
            <Field key={field}>
              <FieldLabel htmlFor={`separator-${field}-${index}`}>
                {t(`separatorSettings.${field}`)}
              </FieldLabel>
              <NativeSelect
                id={`separator-${field}-${index}`}
                defaultValue={fallback}
                {...form.register(`${prefix}.data.${field}` as Path<TValues>)}
              >
                {choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {t(`separatorSettings.${choice}`)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          ))}
        </FieldGroup>
      )}
      <details className="border-t pt-3">
        <summary className="cursor-pointer py-1 text-sm font-medium">
          {t("decorations.title")}
        </summary>
        <div className="pt-4">
          <SectionDecorationFields
            value={decoration}
            onChange={(value) =>
              form.setValue(
                `${prefix}.decoration` as Path<TValues>,
                value as never,
                { shouldDirty: true, shouldValidate: true },
              )
            }
          />
        </div>
      </details>
      <input
        type="hidden"
        {...form.register(`${prefix}.block_type` as Path<TValues>)}
      />
      {type === "core.contact_form" && (
        <p className="text-sm text-muted-foreground">{t("formDeliveryHint")}</p>
      )}
      <FieldGroup>
        {(option?.fields ?? []).map((field) => (
          <BlockField
            assets={assets}
            blockIndex={index}
            field={field}
            form={form}
            key={field.path.join(".")}
            pathPrefix={`${prefix}.data`}
          />
        ))}
      </FieldGroup>
    </fieldset>
  );
}

/** RHF addresses nested values by dot path, and the catalogue field path is
 *  exactly that path inside `data`. */
function fieldName(pathPrefix: string, path: readonly string[]): string {
  return [pathPrefix, ...path].join(".");
}

function fieldErrorMessage<TValues extends FieldValues>(
  form: UseFormReturn<TValues>,
  name: string,
): string | undefined {
  let node: unknown = form.formState.errors;
  for (const segment of name.split(".")) {
    if (!isObject(node as JsonObject) && !Array.isArray(node)) return undefined;
    node = (node as Record<string, unknown>)[segment];
    if (node === undefined) return undefined;
  }
  const message = (node as { message?: unknown } | undefined)?.message;
  return typeof message === "string" ? message : undefined;
}

function BlockField<TValues extends FieldValues>({
  assets = [],
  blockIndex,
  field,
  form,
  pathPrefix,
}: {
  assets?: readonly MediaAsset[];
  blockIndex: number;
  field: BlockFieldDefinition;
  form: UseFormReturn<TValues>;
  pathPrefix: string;
}) {
  const t = useTranslations("Sites");
  const name = fieldName(pathPrefix, field.path);
  const id = `block-${blockIndex}-${name.replace(/[^a-zA-Z0-9]+/g, "-")}`;
  const error = fieldErrorMessage(form, name);

  if (field.kind === "list") {
    return (
      <BlockListField
        assets={assets}
        blockIndex={blockIndex}
        field={field}
        form={form}
        name={name}
      />
    );
  }

  const control =
    field.kind === "media" ? (
      <div className="flex flex-wrap items-center gap-2">
        {/* Only assets that finished scanning: offering a pending one would let
            the operator publish a page whose picture is not there yet. */}
        <NativeSelect
          aria-invalid={Boolean(error)}
          className="flex-1"
          id={id}
          {...form.register(name as never)}
        >
          <option value="">{t("noImage")}</option>
          {assets
            .filter((asset) => asset.state === "ready")
            .map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.original_filename}
              </option>
            ))}
        </NativeSelect>
        {/* Zdjęcie wgrywane w to konkretne miejsce kadrujemy do jego
            proporcji: układ decyduje o ramce, operator o tym, co w niej
            jest (decyzja z 20.09). */}
        {field.aspect ? (
          <ImageCropUpload
            aspect={field.aspect}
            label={t("uploadAndCrop")}
            onUploaded={(assetId) =>
              form.setValue(name as never, assetId as never, {
                shouldDirty: true,
              })
            }
          />
        ) : null}
      </div>
    ) : field.kind === "textarea" ? (
      <Textarea
        aria-invalid={Boolean(error)}
        id={id}
        {...form.register(name as never)}
      />
    ) : (
      <Input
        aria-invalid={Boolean(error)}
        id={id}
        inputMode={field.kind === "url" ? "url" : undefined}
        {...form.register(name as never)}
      />
    );

  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{t(field.labelKey)}</FieldLabel>
      {control}
      <FieldError>{error ? t(error) : undefined}</FieldError>
    </Field>
  );
}

function BlockListField<TValues extends FieldValues>({
  assets = [],
  blockIndex,
  field,
  form,
  name,
}: {
  assets?: readonly MediaAsset[];
  blockIndex: number;
  field: BlockFieldDefinition;
  form: UseFormReturn<TValues>;
  name: string;
}) {
  const t = useTranslations("Sites");
  const entries = useFieldArray({
    control: form.control,
    name: name as never,
  });
  const item = field.item ?? [];
  const error = fieldErrorMessage(form, name);

  return (
    <fieldset className="space-y-3 rounded-lg border border-dashed p-3">
      <legend className="px-1 text-sm font-medium">{t(field.labelKey)}</legend>
      {entries.fields.map((entry, entryIndex) => (
        <div className="space-y-3 rounded-md border p-3" key={entry.id}>
          <div className="flex justify-end">
            <Button
              aria-label={t("removeEntry")}
              onClick={() => entries.remove(entryIndex)}
              size="icon"
              type="button"
              variant="ghost"
            >
              <Trash2Icon aria-hidden="true" />
            </Button>
          </div>
          <FieldGroup>
            {item.map((nested) => (
              <BlockField
                assets={assets}
                blockIndex={blockIndex}
                field={nested}
                form={form}
                key={nested.path.join(".")}
                pathPrefix={`${name}.${entryIndex}`}
              />
            ))}
          </FieldGroup>
        </div>
      ))}
      <Button
        onClick={() => entries.append(emptyFieldData(item) as never)}
        size="sm"
        type="button"
        variant="outline"
      >
        <PlusIcon aria-hidden="true" />
        {t("addEntry")}
      </Button>
      {error ? (
        <p className="text-destructive text-sm" role="alert">
          {t(error)}
        </p>
      ) : null}
    </fieldset>
  );
}

/** A controlled input needs a defined value, so a new block starts with every
 *  field present and blank; `pruneEmpty` removes the untouched ones on save. */
function emptyFieldData(fields: readonly BlockFieldDefinition[]): JsonObject {
  const data: JsonObject = {};
  for (const field of fields) {
    let target = data;
    for (const segment of field.path.slice(0, -1)) {
      const existing = target[segment];
      const nested = isObject(existing) ? existing : {};
      target[segment] = nested;
      target = nested;
    }
    const leaf = field.path[field.path.length - 1];
    target[leaf] = field.kind === "list" ? [] : "";
  }
  return data;
}

export function emptyBlock(type: string): BlockFormValues {
  const option = blockOption(type);
  return {
    block_type: type,
    data: option === undefined ? {} : emptyFieldData(option.fields),
  };
}

/** Fills in the fields the catalogue declares but the stored data omits, so an
 *  optional property that was never set still renders as an empty input. */
function withEditableFields(
  data: JsonObject,
  fields: readonly BlockFieldDefinition[],
): JsonObject {
  // Preserve validated presentation fields that do not use a text form field.
  const merged = { ...emptyFieldData(fields), ...structuredClone(data) };
  for (const field of fields) {
    const stored = readAt(data, field.path);
    if (stored === undefined) continue;
    let target = merged;
    for (const segment of field.path.slice(0, -1)) {
      target = target[segment] as JsonObject;
    }
    const leaf = field.path[field.path.length - 1];
    if (field.kind === "list" && Array.isArray(stored) && field.item) {
      const item = field.item;
      target[leaf] = stored.map((entry) =>
        withEditableFields(isObject(entry) ? entry : {}, item),
      );
    } else {
      target[leaf] = stored;
    }
  }
  return merged;
}

/** Stored blocks, migrated to the current schema and padded out for editing. */
export function editableBlocks(
  blocks: readonly {
    block_type: string;
    schema_version: number;
    data: unknown;
    decoration?: unknown;
  }[],
): BlockFormValues[] {
  return blocks.map((block) => {
    const migrated = registry.migrate(toSiteBlock(block));
    const option = blockOption(migrated.block_type);
    return {
      block_type: migrated.block_type,
      ...(migrated.decoration
        ? { decoration: structuredClone(migrated.decoration) }
        : {}),
      data:
        option === undefined
          ? migrated.data
          : withEditableFields(migrated.data, option.fields),
    };
  });
}

/** The assets the blocks themselves point at.
 *
 *  Collected on save rather than asked of the operator: a picture chosen in a
 *  block and then not listed as a reference would be an asset the page shows
 *  and nothing keeps alive. */
export function mediaIdsInBlocks(blocks: readonly BlockFormValues[]): string[] {
  const found = new Set<string>();
  for (const block of blocks) {
    for (const field of blockOption(block.block_type)?.fields ?? []) {
      collectMedia(block.data, field, found);
    }
  }
  return [...found];
}

function collectMedia(
  data: JsonObject,
  field: BlockFieldDefinition,
  found: Set<string>,
): void {
  if (field.kind === "list") {
    const rows = readAt(data, field.path);
    if (!Array.isArray(rows)) return;
    for (const row of rows) {
      if (!isObject(row)) continue;
      for (const nested of field.item ?? []) collectMedia(row, nested, found);
    }
    return;
  }
  if (field.kind !== "media") return;
  const value = readAt(data, field.path);
  if (typeof value === "string" && value !== "") found.add(value);
}

export function blockPayload(block: BlockFormValues) {
  const pruned = pruneEmpty(block.data);
  return {
    block_type: block.block_type,
    schema_version: blockOption(block.block_type)?.latestVersion ?? 1,
    data: isObject(pruned) ? pruned : {},
    ...(block.decoration !== undefined
      ? { decoration: structuredClone(block.decoration) }
      : {}),
  };
}

export function toSiteBlock(block: {
  block_type: string;
  schema_version: number;
  data: unknown;
  decoration?: unknown;
}): SiteBlock {
  if (!isObject(block.data))
    throw new TypeError("Block data must be an object");
  return {
    block_type: block.block_type,
    schema_version: block.schema_version,
    data: block.data,
    ...(block.decoration != null
      ? { decoration: structuredClone(block.decoration) as SectionDecorationV1 }
      : {}),
  };
}

export function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
