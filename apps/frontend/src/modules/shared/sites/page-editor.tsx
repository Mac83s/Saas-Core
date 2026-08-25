"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useFieldArray,
  useForm,
  useWatch,
  type SubmitHandler,
} from "react-hook-form";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  EyeIcon,
  ImagePlusIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  completeMediaUpload,
  getPageDraft,
  getPageDraftPreview,
  initiateMediaUpload,
  listMediaAssets,
  listPageTranslations,
  savePageDraft,
  savePageTranslation,
  type MediaAsset,
  type PageDraft,
  type PageSummary,
  type PageTranslation,
} from "@saas-core/api-client";
import {
  availablePageTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  InvalidBlockDataError,
  pageTemplateBlocks,
  renderDraftPreview,
  type BlockFieldDefinition,
  type JsonObject,
  type JsonValue,
  type PageTemplate,
  type SiteBlock,
} from "@saas-core/site-blocks";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const designTokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

type BlockFormValues = {
  block_type: string;
  data: JsonObject;
};

/** Every block the library offers, in manifest order. A block without a
 *  `catalog` entry still renders published pages but is not offered here. */
const blockOptions = [...registry.definitions.values()].flatMap((definition) =>
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

type BlockOption = (typeof blockOptions)[number];

function blockOption(blockType: string): BlockOption | undefined {
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
        path: ["data", ...issue.path],
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

const blockFormSchema = z
  .object({
    block_type: z.string(),
    // The shape is whatever the block's own JSON Schema says, so Zod only
    // asserts "an object" here; `refineAgainstBlockContract` is what actually
    // validates it, against the canonical contract.
    data: z.custom<JsonObject>((value) => isObject(value as JsonValue)),
  })
  .superRefine((block, context) => {
    refineAgainstBlockContract(block, context);
  });

const draftSchema = z.object({
  blocks: z.array(blockFormSchema),
  media_asset_ids: z.array(z.string()),
});

type DraftValues = z.infer<typeof draftSchema>;
type TranslationValues = z.infer<ReturnType<typeof createTranslationSchema>>;

export function PageEditor({
  onChanged,
  page,
}: {
  onChanged: () => Promise<void>;
  page: PageSummary;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [draft, setDraft] = useState<PageDraft>();
  const [translations, setTranslations] = useState<PageTranslation[]>([]);
  const [locale, setLocale] = useState("pl");
  const [baseLocale, setBaseLocale] = useState("pl");
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [selectedBlock, setSelectedBlock] = useState<BlockOption | null>(null);
  const [assetOption, setAssetOption] = useState<MediaAsset | null>(null);
  const [preview, setPreview] = useState<PageDraft>();
  const [file, setFile] = useState<File>();
  const [uploadStatus, setUploadStatus] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [draftConflict, setDraftConflict] = useState(false);
  const [translationConflict, setTranslationConflict] = useState(false);
  const draftReceipt = useRef<MutationReceipt | undefined>(undefined);
  const translationReceipt = useRef<MutationReceipt | undefined>(undefined);
  const uploadReceipt = useRef<MutationReceipt | undefined>(undefined);

  const draftForm = useForm<DraftValues>({
    resolver: zodResolver(draftSchema),
    defaultValues: { blocks: [], media_asset_ids: [] },
  });
  const translationSchema = useMemo(() => createTranslationSchema(t), [t]);
  const translationForm = useForm<TranslationValues>({
    resolver: zodResolver(translationSchema),
    defaultValues: emptyTranslation(),
  });
  const blocks = useFieldArray({ control: draftForm.control, name: "blocks" });
  const selectedMediaIds = useWatch({
    control: draftForm.control,
    name: "media_asset_ids",
  });
  const selectedTranslation =
    translations.find((translation) => translation.locale === locale) ?? null;
  const selectableAssets = assets.filter(
    (asset) => asset.state === "ready" && !selectedMediaIds.includes(asset.id),
  );
  // Reaching the editor already means `sites.enabled`; the API stays the
  // boundary, this only avoids offering a template it would refuse.
  const pageTemplates = useMemo(
    () => availablePageTemplates(registry, ["sites.enabled"]),
    [],
  );
  const templateLocale = locale === "en" ? "en" : "pl";

  /** Seeds the recipe into the draft form. Nothing is saved until the operator
   *  reviews it and presses save, so a template applied by mistake costs a
   *  reload, not a version. */
  const applyTemplate = useCallback(
    (template: PageTemplate) => {
      draftForm.setValue(
        "blocks",
        pageTemplateBlocks(template, registry).map((block) => ({
          block_type: block.block_type,
          data: withEditableFields(
            block.data,
            blockOption(block.block_type)?.fields ?? [],
          ),
        })),
        { shouldDirty: true },
      );
    },
    [draftForm],
  );

  const applyLoadedData = useCallback(
    (
      loadedDraft: PageDraft,
      loadedTranslations: PageTranslation[],
      defaultLocale: string,
    ) => {
      setDraft(loadedDraft);
      draftForm.reset(draftValues(loadedDraft));
      setTranslations(loadedTranslations);
      setLocale(defaultLocale);
      setBaseLocale(defaultLocale);
      translationForm.reset(
        translationValues(
          loadedTranslations.find((item) => item.locale === defaultLocale),
          page.key,
        ),
      );
      setPreview(undefined);
      setDraftConflict(false);
      setTranslationConflict(false);
    },
    [draftForm, page.key, translationForm],
  );

  useEffect(() => {
    let mounted = true;
    void Promise.all([
      getPageDraft(page.id),
      listPageTranslations(page.id),
      listMediaAssets(),
    ])
      .then(([loadedDraft, loadedTranslations, loadedAssets]) => {
        if (!mounted) return;
        applyLoadedData(
          loadedDraft,
          loadedTranslations.items,
          loadedTranslations.default_locale,
        );
        setAssets(loadedAssets.items);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [applyLoadedData, page.id, t]);

  const reloadDraft = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      const current = await getPageDraft(page.id);
      setDraft(current);
      draftForm.reset(draftValues(current));
      setDraftConflict(false);
      setPreview(undefined);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }, [draftForm, page.id, t]);

  const handleSaveDraft: SubmitHandler<DraftValues> = async (values) => {
    if (!draft) return;
    setProblem(undefined);
    setDraftConflict(false);
    const input = {
      expected_version: draft.version,
      blocks: values.blocks.map(blockPayload),
      media_asset_ids: values.media_asset_ids,
    };
    try {
      const saved = await savePageDraft(
        page.id,
        input,
        mutationKey(draftReceipt, `draft-${page.id}`, input),
      );
      draftReceipt.current = undefined;
      setDraft(saved);
      draftForm.reset(draftValues(saved));
      setPreview(undefined);
      await onChanged();
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "draft_version_conflict"
      ) {
        setDraftConflict(true);
        return;
      }
      setProblem(sitesErrorMessage(error, t));
    }
  };

  const handleSaveTranslation: SubmitHandler<TranslationValues> = async (
    values,
  ) => {
    const input = {
      ...values,
      expected_version: selectedTranslation?.version ?? 0,
      ...(locale === baseLocale
        ? {
            allow_title_fallback: false,
            allow_description_fallback: false,
            allow_social_title_fallback: false,
            allow_social_description_fallback: false,
          }
        : {}),
    };
    setProblem(undefined);
    setTranslationConflict(false);
    try {
      const saved = await savePageTranslation(
        page.id,
        locale,
        input,
        mutationKey(
          translationReceipt,
          `translation-${page.id}-${locale}`,
          input,
        ),
      );
      translationReceipt.current = undefined;
      setTranslations((current) => [
        ...current.filter((item) => item.locale !== saved.locale),
        saved,
      ]);
      translationForm.reset(translationValues(saved, page.key));
      await onChanged();
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "translation_version_conflict"
      ) {
        setTranslationConflict(true);
        return;
      }
      setProblem(sitesErrorMessage(error, t));
    }
  };

  async function showPreview() {
    if (!draft?.draft_id) return;
    setLoading(true);
    setProblem(undefined);
    try {
      setPreview(await getPageDraftPreview(page.id, draft.draft_id));
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }

  async function uploadFile() {
    if (!file) return;
    const input = {
      filename: file.name,
      content_type: file.type,
      size: file.size,
    };
    setLoading(true);
    setProblem(undefined);
    setUploadStatus(undefined);
    try {
      const intent = await initiateMediaUpload(
        input,
        mutationKey(uploadReceipt, "media-upload", input),
      );
      const uploaded = await fetch(intent.upload_url, {
        method: "PUT",
        headers: intent.upload_headers,
        body: file,
      });
      if (!uploaded.ok)
        throw new Error(`Upload zwrócił status ${uploaded.status}`);
      const asset = await completeMediaUpload(intent.asset.id);
      uploadReceipt.current = undefined;
      setUploadStatus(t("mediaProcessing", { state: asset.state }));
      setFile(undefined);
      setAssets((await listMediaAssets()).items);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }

  const renderedPreview = useMemo(() => {
    if (!preview?.draft_id) return null;
    return renderDraftPreview(
      {
        kind: "draft-preview",
        versionId: preview.draft_id,
        blocks: preview.blocks.map(toSiteBlock),
        designTokens,
      },
      registry,
    );
  }, [preview]);

  return (
    <div className="space-y-6">
      {problem && (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("contentEditor")}</CardTitle>
          <CardDescription>
            {t("contentEditorDescription", { page: page.name })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-5"
            onSubmit={(event) => {
              void draftForm.handleSubmit(handleSaveDraft)(event);
            }}
          >
            {draftConflict && (
              <div
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4"
                role="alert"
              >
                <p className="text-sm text-destructive">{t("draftConflict")}</p>
                <Button
                  autoFocus
                  onClick={() => void reloadDraft()}
                  type="button"
                  variant="outline"
                >
                  <RefreshCwIcon aria-hidden="true" />
                  {t("loadServerVersion")}
                </Button>
              </div>
            )}

            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field className="flex-1">
                <FieldLabel htmlFor="block-picker">{t("addBlock")}</FieldLabel>
                <Combobox
                  isItemEqualToValue={(item, value) => item.type === value.type}
                  itemToStringLabel={(item) => t(item.labelKey)}
                  itemToStringValue={(item) => item.type}
                  items={blockOptions}
                  onValueChange={setSelectedBlock}
                  value={selectedBlock}
                >
                  <ComboboxInput
                    id="block-picker"
                    placeholder={t("searchBlocks")}
                    triggerLabel={t("openOptions")}
                  />
                  <ComboboxContent>
                    <ComboboxEmpty>{t("noBlocks")}</ComboboxEmpty>
                    <ComboboxList>
                      {blockOptions.map((option) => (
                        <ComboboxItem key={option.type} value={option}>
                          {t(option.labelKey)}
                        </ComboboxItem>
                      ))}
                    </ComboboxList>
                  </ComboboxContent>
                </Combobox>
              </Field>
              <Button
                disabled={!selectedBlock}
                onClick={() => {
                  if (!selectedBlock) return;
                  blocks.append(emptyBlock(selectedBlock.type));
                  setSelectedBlock(null);
                }}
                type="button"
                variant="outline"
              >
                <PlusIcon aria-hidden="true" />
                {t("add")}
              </Button>
            </div>

            <div className="space-y-4">
              {blocks.fields.length === 0 && (
                <div className="space-y-4 rounded-lg border border-dashed p-4">
                  <p className="text-sm text-muted-foreground">
                    {t("emptyBlocks")}
                  </p>
                  <div>
                    <h3 className="font-medium">{t("startFromTemplate")}</h3>
                    <p className="text-sm text-muted-foreground">
                      {t("startFromTemplateDescription")}
                    </p>
                  </div>
                  <ul className="grid gap-3 sm:grid-cols-3">
                    {pageTemplates.map((template) => (
                      <li key={template.id}>
                        <Card className="h-full">
                          <CardHeader>
                            <CardTitle className="text-base">
                              {template.labels[templateLocale].name}
                            </CardTitle>
                            <CardDescription>
                              {template.labels[templateLocale].description}
                            </CardDescription>
                          </CardHeader>
                          <CardContent>
                            <Button
                              aria-label={t("useNamedTemplate", {
                                name: template.labels[templateLocale].name,
                              })}
                              onClick={() => applyTemplate(template)}
                              type="button"
                              variant="outline"
                            >
                              {t("useTemplate")}
                            </Button>
                          </CardContent>
                        </Card>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {blocks.fields.map((field, index) => (
                <BlockFields
                  form={draftForm}
                  index={index}
                  key={field.id}
                  moveDown={() => blocks.swap(index, index + 1)}
                  moveUp={() => blocks.swap(index, index - 1)}
                  onRemove={() => blocks.remove(index)}
                  type={field.block_type}
                  isFirst={index === 0}
                  isLast={index === blocks.fields.length - 1}
                />
              ))}
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <div>
                <h3 className="font-medium">{t("media")}</h3>
                <p className="text-sm text-muted-foreground">
                  {t("mediaDescription")}
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <Field className="flex-1">
                  <FieldLabel htmlFor="media-picker">
                    {t("chooseMedia")}
                  </FieldLabel>
                  <Combobox
                    isItemEqualToValue={(item, value) => item.id === value.id}
                    itemToStringLabel={(item) => item.original_filename}
                    itemToStringValue={(item) => item.id}
                    items={selectableAssets}
                    onValueChange={setAssetOption}
                    value={assetOption}
                  >
                    <ComboboxInput
                      id="media-picker"
                      placeholder={t("searchMedia")}
                      triggerLabel={t("openOptions")}
                    />
                    <ComboboxContent>
                      <ComboboxEmpty>{t("noReadyMedia")}</ComboboxEmpty>
                      <ComboboxList>
                        {selectableAssets.map((asset) => (
                          <ComboboxItem key={asset.id} value={asset}>
                            {asset.original_filename}
                          </ComboboxItem>
                        ))}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                </Field>
                <Button
                  disabled={!assetOption}
                  onClick={() => {
                    if (!assetOption) return;
                    draftForm.setValue(
                      "media_asset_ids",
                      [...selectedMediaIds, assetOption.id],
                      { shouldDirty: true },
                    );
                    setAssetOption(null);
                  }}
                  type="button"
                  variant="outline"
                >
                  <PlusIcon aria-hidden="true" />
                  {t("add")}
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedMediaIds.map((assetId) => {
                  const asset = assets.find((item) => item.id === assetId);
                  return (
                    <Badge key={assetId} variant="secondary">
                      {asset?.original_filename ?? assetId}
                      <button
                        aria-label={t("removeMedia", {
                          name: asset?.original_filename ?? assetId,
                        })}
                        className="ml-1 rounded p-0.5 hover:bg-background"
                        onClick={() =>
                          draftForm.setValue(
                            "media_asset_ids",
                            selectedMediaIds.filter((id) => id !== assetId),
                            { shouldDirty: true },
                          )
                        }
                        type="button"
                      >
                        <Trash2Icon aria-hidden="true" className="size-3" />
                      </button>
                    </Badge>
                  );
                })}
              </div>
              <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                <Field>
                  <FieldLabel htmlFor="media-upload">
                    {t("uploadImage")}
                  </FieldLabel>
                  <Input
                    accept="image/jpeg,image/png,image/webp"
                    id="media-upload"
                    onChange={(event) => setFile(event.target.files?.[0])}
                    type="file"
                  />
                </Field>
                <Button
                  disabled={!file || loading}
                  onClick={() => void uploadFile()}
                  type="button"
                  variant="outline"
                >
                  <ImagePlusIcon aria-hidden="true" />
                  {t("upload")}
                </Button>
              </div>
              {uploadStatus && (
                <p className="text-sm text-muted-foreground" role="status">
                  {uploadStatus}
                </p>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button disabled={loading || draftConflict} type="submit">
                <SaveIcon aria-hidden="true" />
                {t("saveDraft")}
              </Button>
              <Button
                disabled={loading || !draft?.draft_id}
                onClick={() => void showPreview()}
                type="button"
                variant="outline"
              >
                <EyeIcon aria-hidden="true" />
                {t("preview")}
              </Button>
              <Badge variant="outline">
                {t("versionValue", { version: draft?.version ?? 0 })}
              </Badge>
            </div>
          </form>
        </CardContent>
      </Card>

      {renderedPreview && (
        <Card>
          <CardHeader>
            <CardTitle>{t("preview")}</CardTitle>
            <CardDescription>{t("previewDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div
              className="rounded-lg border bg-background p-6"
              data-testid="draft-preview"
            >
              {renderedPreview}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("metadata")}</CardTitle>
          <CardDescription>{t("metadataDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-5"
            onSubmit={(event) => {
              void translationForm.handleSubmit(handleSaveTranslation)(event);
            }}
          >
            <Field>
              <FieldLabel htmlFor="translation-locale">
                {t("locale")}
              </FieldLabel>
              <Select
                onValueChange={(nextLocale) => {
                  if (!nextLocale) return;
                  setLocale(nextLocale);
                  setTranslationConflict(false);
                  translationReceipt.current = undefined;
                  translationForm.reset(
                    translationValues(
                      translations.find((item) => item.locale === nextLocale),
                      page.key,
                    ),
                  );
                }}
                value={locale}
              >
                <SelectTrigger className="w-full" id="translation-locale">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pl">{common("polish")}</SelectItem>
                  <SelectItem value="en">{common("english")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            {translationConflict && (
              <div
                className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
                role="alert"
              >
                {t("translationConflict")}
              </div>
            )}

            <FieldGroup>
              <TranslationTextField
                disabled={Boolean(selectedTranslation?.slug_locked)}
                form={translationForm}
                id="translation-slug"
                label={t("slug")}
                name="slug"
              />
              <TranslationTextField
                form={translationForm}
                id="translation-title"
                label={t("metaTitle")}
                name="title"
              />
              <TranslationTextareaField
                form={translationForm}
                id="translation-description"
                label={t("metaDescription")}
                name="description"
              />
              <TranslationTextField
                form={translationForm}
                id="translation-social-title"
                label={t("socialTitle")}
                name="social_title"
              />
              <TranslationTextareaField
                form={translationForm}
                id="translation-social-description"
                label={t("socialDescription")}
                name="social_description"
              />
            </FieldGroup>

            {locale !== baseLocale && (
              <fieldset className="space-y-2 rounded-lg border p-4">
                <legend className="px-1 text-sm font-medium">
                  {t("fallbacks")}
                </legend>
                {(
                  [
                    ["allow_title_fallback", "metaTitle"],
                    ["allow_description_fallback", "metaDescription"],
                    ["allow_social_title_fallback", "socialTitle"],
                    ["allow_social_description_fallback", "socialDescription"],
                  ] as const
                ).map(([name, label]) => (
                  <label className="flex items-center gap-2 text-sm" key={name}>
                    <input
                      type="checkbox"
                      {...translationForm.register(name)}
                    />
                    {t("allowFallback", { field: t(label) })}
                  </label>
                ))}
              </fieldset>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={loading || translationConflict} type="submit">
                <SaveIcon aria-hidden="true" />
                {t("saveMetadata")}
              </Button>
              <Badge variant="outline">
                {t("versionValue", {
                  version: selectedTranslation?.version ?? 0,
                })}
              </Badge>
              {selectedTranslation?.slug_locked && (
                <Badge variant="secondary">{t("slugLocked")}</Badge>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function BlockFields({
  form,
  index,
  isFirst,
  isLast,
  moveDown,
  moveUp,
  onRemove,
  type,
}: {
  form: ReturnType<typeof useForm<DraftValues>>;
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
      <input type="hidden" {...form.register(`${prefix}.block_type`)} />
      <FieldGroup>
        {(option?.fields ?? []).map((field) => (
          <BlockField
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

type DraftForm = ReturnType<typeof useForm<DraftValues>>;

/** RHF addresses nested values by dot path, and the catalogue field path is
 *  exactly that path inside `data`. */
function fieldName(pathPrefix: string, path: readonly string[]): string {
  return [pathPrefix, ...path].join(".");
}

function fieldErrorMessage(form: DraftForm, name: string): string | undefined {
  let node: unknown = form.formState.errors;
  for (const segment of name.split(".")) {
    if (!isObject(node as JsonObject) && !Array.isArray(node)) return undefined;
    node = (node as Record<string, unknown>)[segment];
    if (node === undefined) return undefined;
  }
  const message = (node as { message?: unknown } | undefined)?.message;
  return typeof message === "string" ? message : undefined;
}

function BlockField({
  blockIndex,
  field,
  form,
  pathPrefix,
}: {
  blockIndex: number;
  field: BlockFieldDefinition;
  form: DraftForm;
  pathPrefix: string;
}) {
  const t = useTranslations("Sites");
  const name = fieldName(pathPrefix, field.path);
  const id = `block-${blockIndex}-${name.replace(/[^a-zA-Z0-9]+/g, "-")}`;
  const error = fieldErrorMessage(form, name);

  if (field.kind === "list") {
    return (
      <BlockListField
        blockIndex={blockIndex}
        field={field}
        form={form}
        name={name}
      />
    );
  }

  const control =
    field.kind === "textarea" ? (
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

function BlockListField({
  blockIndex,
  field,
  form,
  name,
}: {
  blockIndex: number;
  field: BlockFieldDefinition;
  form: DraftForm;
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

function TranslationTextField({
  disabled,
  form,
  id,
  label,
  name,
}: {
  disabled?: boolean;
  form: ReturnType<typeof useForm<TranslationValues>>;
  id: string;
  label: string;
  name: "slug" | "title" | "social_title";
}) {
  const error = form.formState.errors[name]?.message;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(error)}
        disabled={disabled}
        id={id}
        {...form.register(name)}
      />
      <FieldError>{error}</FieldError>
    </Field>
  );
}

function TranslationTextareaField({
  form,
  id,
  label,
  name,
}: {
  form: ReturnType<typeof useForm<TranslationValues>>;
  id: string;
  label: string;
  name: "description" | "social_description";
}) {
  const error = form.formState.errors[name]?.message;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Textarea
        aria-invalid={Boolean(error)}
        id={id}
        {...form.register(name)}
      />
      <FieldError>{error}</FieldError>
    </Field>
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

function emptyBlock(type: string): BlockFormValues {
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
  const merged = structuredClone(emptyFieldData(fields));
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

function draftValues(draft: PageDraft): DraftValues {
  return {
    blocks: draft.blocks.map((block) => {
      const migrated = registry.migrate(toSiteBlock(block));
      const option = blockOption(migrated.block_type);
      return {
        block_type: migrated.block_type,
        data:
          option === undefined
            ? migrated.data
            : withEditableFields(migrated.data, option.fields),
      };
    }),
    media_asset_ids: draft.media_asset_ids,
  };
}

function blockPayload(block: BlockFormValues) {
  const pruned = pruneEmpty(block.data);
  return {
    block_type: block.block_type,
    schema_version: blockOption(block.block_type)?.latestVersion ?? 1,
    data: isObject(pruned) ? pruned : {},
  };
}

function toSiteBlock(block: {
  block_type: string;
  schema_version: number;
  data: unknown;
}): SiteBlock {
  if (!isObject(block.data))
    throw new TypeError("Block data must be an object");
  return {
    block_type: block.block_type,
    schema_version: block.schema_version,
    data: block.data,
  };
}

function translationValues(
  translation: PageTranslation | undefined,
  fallbackSlug: string,
): TranslationValues {
  if (!translation) return { ...emptyTranslation(), slug: fallbackSlug };
  return {
    slug: translation.slug,
    title: translation.title,
    description: translation.description,
    social_title: translation.social_title,
    social_description: translation.social_description,
    allow_title_fallback: translation.allow_title_fallback,
    allow_description_fallback: translation.allow_description_fallback,
    allow_social_title_fallback: translation.allow_social_title_fallback,
    allow_social_description_fallback:
      translation.allow_social_description_fallback,
  };
}

function emptyTranslation(): TranslationValues {
  return {
    slug: "",
    title: "",
    description: "",
    social_title: "",
    social_description: "",
    allow_title_fallback: false,
    allow_description_fallback: false,
    allow_social_title_fallback: false,
    allow_social_description_fallback: false,
  };
}

function createTranslationSchema(
  t: ReturnType<typeof useTranslations<"Sites">>,
) {
  return z.object({
    slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
    title: z.string().max(160, t("maxCharacters", { count: 160 })),
    description: z.string().max(320, t("maxCharacters", { count: 320 })),
    social_title: z.string().max(160, t("maxCharacters", { count: 160 })),
    social_description: z.string().max(320, t("maxCharacters", { count: 320 })),
    allow_title_fallback: z.boolean(),
    allow_description_fallback: z.boolean(),
    allow_social_title_fallback: z.boolean(),
    allow_social_description_fallback: z.boolean(),
  });
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
