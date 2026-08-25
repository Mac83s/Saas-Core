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
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  InvalidBlockDataError,
  renderDraftPreview,
  type JsonObject,
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

type BlockOption = {
  type: "core.hero" | "core.rich_text";
  labelKey: "heroBlock" | "richTextBlock";
};

type BlockFormValues = {
  block_type: "core.hero" | "core.rich_text";
  title: string;
  text: string;
  action_label: string;
  action_href: string;
};

const blockOptions: BlockOption[] = [
  { type: "core.hero", labelKey: "heroBlock" },
  { type: "core.rich_text", labelKey: "richTextBlock" },
];

/** The form is flat — `action_label` / `action_href` — while the canonical
 *  block schema nests them under `action`. */
const FIELD_BY_POINTER: Record<string, keyof BlockFormValues> = {
  title: "title",
  text: "text",
  action: "action_label",
  "action/label": "action_label",
  "action/href": "action_href",
};

const MESSAGE_BY_KEYWORD: Record<string, string> = {
  required: "required",
  minLength: "required",
  maxLength: "tooLong",
  pattern: "invalidHref",
};

/** Field limits and formats live in the canonical JSON Schema (ADR-027). The
 *  form validates by asking the registry rather than restating them here: a
 *  second copy drifts, and the drift is only discovered when the backend
 *  rejects a draft the panel had already accepted. */
function refineAgainstBlockContract(
  block: BlockFormValues,
  context: z.RefinementCtx,
): void {
  try {
    registry.validate(toSiteBlock(blockPayload(block)));
  } catch (error) {
    if (!(error instanceof InvalidBlockDataError)) throw error;
    for (const issue of error.issues) {
      const field = FIELD_BY_POINTER[issue.path.join("/")];
      if (field === undefined) continue;
      context.addIssue({
        code: "custom",
        path: [field],
        message: MESSAGE_BY_KEYWORD[issue.keyword] ?? "invalid",
      });
    }
  }
}

const blockFormSchema = z
  .object({
    block_type: z.enum(["core.hero", "core.rich_text"]),
    title: z.string(),
    text: z.string(),
    action_label: z.string(),
    action_href: z.string(),
  })
  .superRefine((block, context) => {
    refineAgainstBlockContract(block, context);
    // Not expressible in the block schema: `action` is optional as a whole, so
    // a half-filled call to action validates only because it is dropped from
    // the payload. The editor has to catch that before it disappears.
    if (block.action_href.trim() && !block.action_label.trim()) {
      context.addIssue({
        code: "custom",
        path: ["action_label"],
        message: "required",
      });
    }
    if (block.action_label.trim() && !block.action_href.trim()) {
      context.addIssue({
        code: "custom",
        path: ["action_href"],
        message: "required",
      });
    }
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
  const [blockOption, setBlockOption] = useState<BlockOption | null>(null);
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
                  onValueChange={setBlockOption}
                  value={blockOption}
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
                disabled={!blockOption}
                onClick={() => {
                  if (!blockOption) return;
                  blocks.append(emptyBlock(blockOption.type));
                  setBlockOption(null);
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
                <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  {t("emptyBlocks")}
                </p>
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
  type: DraftValues["blocks"][number]["block_type"];
}) {
  const t = useTranslations("Sites");
  const prefix = `blocks.${index}` as const;
  return (
    <fieldset className="space-y-4 rounded-lg border p-4">
      <legend className="px-1 font-medium">
        {t(type === "core.hero" ? "heroBlock" : "richTextBlock")}
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
      {type === "core.hero" ? (
        <FieldGroup>
          <DraftInput
            form={form}
            id={`block-${index}-title`}
            label={t("heading")}
            name={`${prefix}.title`}
          />
          <DraftTextarea
            form={form}
            id={`block-${index}-text`}
            label={t("text")}
            name={`${prefix}.text`}
          />
          <DraftInput
            form={form}
            id={`block-${index}-action-label`}
            label={t("actionLabel")}
            name={`${prefix}.action_label`}
          />
          <DraftInput
            form={form}
            id={`block-${index}-action-href`}
            label={t("actionHref")}
            name={`${prefix}.action_href`}
          />
        </FieldGroup>
      ) : (
        <DraftTextarea
          form={form}
          id={`block-${index}-rich-text`}
          label={t("text")}
          name={`${prefix}.text`}
        />
      )}
    </fieldset>
  );
}

function DraftInput({
  form,
  id,
  label,
  name,
}: {
  form: ReturnType<typeof useForm<DraftValues>>;
  id: string;
  label: string;
  name: `blocks.${number}.${"title" | "action_label" | "action_href"}`;
}) {
  const t = useTranslations("Sites");
  const error =
    form.formState.errors.blocks?.[Number(name.split(".")[1])]?.[
      name.split(".")[2] as "title" | "action_label" | "action_href"
    ]?.message;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input aria-invalid={Boolean(error)} id={id} {...form.register(name)} />
      <FieldError>{error ? t(error) : undefined}</FieldError>
    </Field>
  );
}

function DraftTextarea({
  form,
  id,
  label,
  name,
}: {
  form: ReturnType<typeof useForm<DraftValues>>;
  id: string;
  label: string;
  name: `blocks.${number}.text`;
}) {
  const t = useTranslations("Sites");
  const error =
    form.formState.errors.blocks?.[Number(name.split(".")[1])]?.text?.message;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Textarea
        aria-invalid={Boolean(error)}
        id={id}
        {...form.register(name)}
      />
      <FieldError>{error ? t(error) : undefined}</FieldError>
    </Field>
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

function emptyBlock(type: BlockOption["type"]): DraftValues["blocks"][number] {
  return {
    block_type: type,
    title: "",
    text: "",
    action_label: "",
    action_href: "",
  };
}

function draftValues(draft: PageDraft): DraftValues {
  return {
    blocks: draft.blocks.map((block) => {
      const migrated = registry.migrate(toSiteBlock(block));
      if (migrated.block_type === "core.hero") {
        const action = isObject(migrated.data.action)
          ? migrated.data.action
          : {};
        return {
          block_type: "core.hero" as const,
          title: stringValue(migrated.data.title),
          text: stringValue(migrated.data.text),
          action_label: stringValue(action.label),
          action_href: stringValue(action.href),
        };
      }
      return {
        block_type: "core.rich_text" as const,
        title: "",
        text: stringValue(migrated.data.text),
        action_label: "",
        action_href: "",
      };
    }),
    media_asset_ids: draft.media_asset_ids,
  };
}

function blockPayload(block: DraftValues["blocks"][number]) {
  if (block.block_type === "core.hero") {
    const data: JsonObject = { title: block.title.trim() };
    if (block.text.trim()) data.text = block.text.trim();
    if (block.action_label.trim() && block.action_href.trim()) {
      data.action = {
        label: block.action_label.trim(),
        href: block.action_href.trim(),
      };
    }
    return { block_type: block.block_type, schema_version: 2, data };
  }
  return {
    block_type: block.block_type,
    schema_version: 1,
    data: { text: block.text.trim() },
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

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}
