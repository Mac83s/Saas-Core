"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useFieldArray,
  useForm,
  useWatch,
  type SubmitHandler,
} from "react-hook-form";
import {
  MonitorIcon,
  EyeIcon,
  ImagePlusIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  SmartphoneIcon,
  TabletIcon,
  Trash2Icon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  completeMediaUpload,
  getPageDraft,
  getPageDraftPreview,
  importPageTemplate,
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
  renderDraftPreview,
  type PageTemplate,
  type SiteAppearance,
  type NavigationLink,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
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

import {
  BlockFields,
  blockFormSchema,
  blockOptions,
  blockPayload,
  editableBlocks,
  mediaIdsInBlocks,
  emptyBlock,
  registry,
  toSiteBlock,
  type BlockOption,
} from "./block-form";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { renderPrivateMedia } from "./private-media-preview";
import { SectionCanvas } from "./section-canvas";
import { useDraftHistory } from "./draft-history";
import { pageTemplatePreview } from "./template-media-preview";
import { SectionLibrary, SectionLibraryContent } from "./section-library";
import { PageUrlDialog } from "./page-url";
import { sitesErrorMessage } from "./problem";

const designTokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

const draftSchema = z.object({
  blocks: z.array(blockFormSchema),
  media_asset_ids: z.array(z.string()),
});

type DraftValues = z.infer<typeof draftSchema>;
type TranslationValues = z.infer<ReturnType<typeof createTranslationSchema>>;
type PreviewViewport = "desktop" | "tablet" | "mobile";

const previewWidths: Record<PreviewViewport, string> = {
  desktop: "100%",
  tablet: "768px",
  mobile: "390px",
};

function TemplateOption({
  closeLabel,
  loading,
  locale,
  onApply,
  previewLabel,
  previewTitle,
  template,
  thumbnailLabel,
  useLabel,
}: {
  closeLabel: string;
  loading: boolean;
  locale: "pl" | "en";
  onApply: () => void;
  previewLabel: string;
  previewTitle: string;
  template: PageTemplate;
  thumbnailLabel: string;
  useLabel: string;
}) {
  const label = template.labels[locale];
  const preview = pageTemplatePreview(template, locale);
  const rendered = renderDraftPreview(
    {
      kind: "draft-preview",
      versionId: `template:${template.id}:v${template.version}`,
      blocks: preview.blocks,
      designTokens,
    },
    registry,
    preview.imageRenderer,
  );

  return (
    <Card className="h-full overflow-hidden">
      <div
        aria-label={thumbnailLabel}
        className="relative h-40 overflow-hidden border-b bg-muted/30"
        role="img"
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 w-[960px] origin-top-left scale-[0.32]"
          inert
        >
          {rendered}
        </div>
        <div className="absolute inset-x-0 bottom-0 bg-background/95 px-4 py-3 shadow-[0_-8px_24px_hsl(var(--background))]">
          <p className="font-medium">{label.name}</p>
          <p className="line-clamp-1 text-xs text-muted-foreground">
            {label.description}
          </p>
        </div>
      </div>
      <CardHeader>
        <CardTitle className="text-base">{label.name}</CardTitle>
        <CardDescription>{label.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2">
        <Dialog>
          <DialogTrigger
            render={
              <Button className="w-full" type="button" variant="outline" />
            }
          >
            <EyeIcon aria-hidden="true" />
            {previewLabel}
          </DialogTrigger>
          <DialogContent
            className="max-h-[90vh] max-w-4xl overflow-y-auto"
            closeLabel={closeLabel}
          >
            <DialogHeader>
              <DialogTitle>{previewTitle}</DialogTitle>
              <DialogDescription>{label.description}</DialogDescription>
            </DialogHeader>
            <div
              aria-label={previewTitle}
              className="overflow-hidden rounded-xl border bg-background p-5 [&_a]:underline [&_address]:space-y-2 [&_address]:not-italic [&_h1]:text-3xl [&_h1]:font-semibold [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:font-medium [&_li]:mt-2 [&_main]:space-y-5 [&_p]:mt-2 [&_section]:rounded-lg [&_section]:border [&_section]:p-5"
              role="img"
            >
              <div aria-hidden="true" inert>
                {rendered}
              </div>
            </div>
          </DialogContent>
        </Dialog>
        <Button
          aria-label={useLabel}
          disabled={loading}
          onClick={onApply}
          type="button"
        >
          {useLabel}
        </Button>
      </CardContent>
    </Card>
  );
}

export function PageEditor({
  onChanged,
  onExitStateChange,
  appearance,
  appearanceControls,
  savedAppearance,
  navigation,
  page,
}: {
  onChanged: () => Promise<void>;
  onExitStateChange?: (state: { dirty: boolean; busy: boolean }) => void;
  page: PageSummary;
  appearance?: SiteAppearance;
  savedAppearance?: SiteAppearance;
  navigation?: readonly NavigationLink[];
  appearanceControls?: ReactNode;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const interfaceLocale = useLocale();
  const [draft, setDraft] = useState<PageDraft>();
  const [translations, setTranslations] = useState<PageTranslation[]>([]);
  const [locale, setLocale] = useState("pl");
  const [baseLocale, setBaseLocale] = useState("pl");
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [selectedBlock, setSelectedBlock] = useState<BlockOption | null>(null);
  const [assetOption, setAssetOption] = useState<MediaAsset | null>(null);
  const [preview, setPreview] = useState<PageDraft>();
  const [previewViewport, setPreviewViewport] =
    useState<PreviewViewport>("desktop");
  const [file, setFile] = useState<File>();
  const [uploadStatus, setUploadStatus] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [draftConflict, setDraftConflict] = useState(false);
  const [translationConflict, setTranslationConflict] = useState(false);
  const draftReceipt = useRef<MutationReceipt | undefined>(undefined);
  const translationReceipt = useRef<MutationReceipt | undefined>(undefined);
  const uploadReceipt = useRef<MutationReceipt | undefined>(undefined);
  const templateReceipt = useRef<MutationReceipt | undefined>(undefined);

  const draftForm = useForm<DraftValues>({
    resolver: zodResolver(draftSchema),
    defaultValues: { blocks: [], media_asset_ids: [] },
  });
  const translationSchema = useMemo(() => createTranslationSchema(t), [t]);
  const translationForm = useForm<TranslationValues>({
    resolver: zodResolver(translationSchema),
    defaultValues: emptyTranslation(),
  });
  const dirty =
    draftForm.formState.isDirty ||
    translationForm.formState.isDirty ||
    Boolean(file);
  const busy =
    loading ||
    draftForm.formState.isSubmitting ||
    translationForm.formState.isSubmitting;
  useEffect(() => {
    onExitStateChange?.({ dirty, busy });
  }, [dirty, busy, onExitStateChange]);
  useEffect(() => {
    if (!dirty) return;
    const preventLoss = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [dirty]);
  const blocks = useFieldArray({ control: draftForm.control, name: "blocks" });
  const liveBlocks = useWatch({ control: draftForm.control, name: "blocks" });
  const history = useDraftHistory(draftForm);
  const [visual, setVisual] = useState(true);
  const [mediaOpen, setMediaOpen] = useState(false);
  const [mediaProblem, setMediaProblem] = useState<string>();
  const [metadataProblem, setMetadataProblem] = useState<string>();
  const [inspectorRequest, setInspectorRequest] = useState(0);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [replacementTemplate, setReplacementTemplate] =
    useState<PageTemplate | null>(null);
  const [selectedSection, setSelectedSection] = useState(0);
  const activeSection = Math.min(
    selectedSection,
    Math.max(0, blocks.fields.length - 1),
  );
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
  const templateLocale = interfaceLocale === "en" ? "en" : "pl";

  const applyTemplate = useCallback(
    async (template: PageTemplate) => {
      if (!draft) return;
      const input = {
        expected_version: draft.version,
        template_id: template.id,
        template_version: template.version,
        locale: templateLocale,
      } as const;
      setLoading(true);
      setProblem(undefined);
      setDraftConflict(false);
      try {
        const imported = await importPageTemplate(
          page.id,
          input,
          mutationKey(templateReceipt, `template-${page.id}`, input),
        );
        templateReceipt.current = undefined;
        setDraft(imported);
        draftForm.reset(draftValues(imported));
        setPreview(undefined);
        setAssets((await listMediaAssets()).items);
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
      } finally {
        setLoading(false);
      }
    },
    [draft, draftForm, onChanged, page.id, t, templateLocale],
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

  // The URL change happens outside both forms and bumps the translation
  // version, so the loaded copy has to come back or the next metadata save
  // would collide with a version it never saw.
  const reloadTranslations = useCallback(async () => {
    const loaded = await listPageTranslations(page.id);
    setTranslations(loaded.items);
    translationReceipt.current = undefined;
    setTranslationConflict(false);
    translationForm.reset(
      translationValues(
        loaded.items.find((item) => item.locale === locale),
        page.key,
      ),
    );
  }, [locale, page.id, page.key, translationForm]);

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
      // A picture chosen inside a block is referenced whether or not the
      // operator also listed it below: an asset the page shows and nothing
      // keeps alive is one storage is free to reclaim.
      media_asset_ids: [
        ...new Set([
          ...values.media_asset_ids,
          ...mediaIdsInBlocks(values.blocks),
        ]),
      ],
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
    setMetadataProblem(undefined);
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
      setMetadataProblem(sitesErrorMessage(error, t));
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
    setMediaProblem(undefined);
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
      setMediaProblem(sitesErrorMessage(error, t));
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
        appearance: savedAppearance,
        blocks: preview.blocks.map(toSiteBlock),
        designTokens,
      },
      registry,
      renderPrivateMedia,
    );
  }, [preview, savedAppearance]);

  const blockPicker = (afterSelected: boolean) => (
    <div
      className={
        afterSelected
          ? "grid gap-3"
          : "flex flex-col gap-3 sm:flex-row sm:items-end"
      }
    >
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
          const position = afterSelected
            ? activeSection + 1
            : blocks.fields.length;
          blocks.insert(position, emptyBlock(selectedBlock.type));
          setSelectedSection(position);
          setSelectedBlock(null);
        }}
        type="button"
        variant="outline"
      >
        <PlusIcon aria-hidden="true" />
        {t("add")}
      </Button>
    </div>
  );

  return (
    <div className="site-studio-editor">
      {problem && (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </div>
      )}

      <Card className="studio-editor-main">
        <CardContent className="studio-editor-content">
          <form
            className="studio-editor-form"
            onSubmit={(event) => {
              void draftForm.handleSubmit(handleSaveDraft, (errors) => {
                const first = Object.keys(errors.blocks ?? {}).find((key) =>
                  /^\d+$/.test(key),
                );
                if (first !== undefined) {
                  setSelectedSection(Number(first));
                  setInspectorRequest((request) => request + 1);
                  setProblem(t("studio.validationError"));
                }
              })(event);
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

            <fieldset
              disabled={loading || draftForm.formState.isSubmitting}
              className="studio-editor-fieldset"
            >
              <div className="studio-toolbar">
                <Button
                  type="button"
                  variant="outline"
                  aria-pressed={visual}
                  onClick={() => setVisual(true)}
                >
                  {t("studio.visual")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  aria-pressed={!visual}
                  onClick={() => setVisual(false)}
                >
                  {t("studio.forms")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!history.canUndo}
                  onClick={history.undo}
                >
                  {t("studio.undo")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!history.canRedo}
                  onClick={history.redo}
                >
                  {t("studio.redo")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setMediaOpen(true)}
                >
                  {t("media")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setMetadataOpen(true)}
                >
                  {t("studio.pageSettings")}
                </Button>
                <div className="studio-save-actions">
                  <Button disabled={loading || draftConflict} type="submit">
                    <SaveIcon aria-hidden="true" />
                    {t("studio.save")}
                  </Button>
                  <Button
                    disabled={loading || !draft?.draft_id}
                    onClick={() => void showPreview()}
                    type="button"
                    variant="outline"
                    aria-label={t("preview")}
                    title={t("preview")}
                  >
                    <EyeIcon aria-hidden="true" />
                    <span className="hidden sm:inline">{t("preview")}</span>
                  </Button>
                  <Badge variant="outline">
                    {t("versionValue", { version: draft?.version ?? 0 })}
                  </Badge>
                </div>
              </div>
              <div
                className={`studio-editing-body ${visual ? "" : "studio-form-list"}`}
              >
                {!visual && (
                  <>
                    {appearanceControls && (
                      <details className="rounded-lg border p-3">
                        <summary className="cursor-pointer font-semibold">
                          {t("appearance.title")}
                        </summary>
                        {appearanceControls}
                      </details>
                    )}
                    <SectionLibrary
                      onBusyChange={setLoading}
                      onAdd={(block) => {
                        if (block.data.image)
                          void listMediaAssets()
                            .then((result) => setAssets(result.items))
                            .catch(() => {});
                        blocks.append(block);
                        setSelectedSection(blocks.fields.length);
                      }}
                    />
                    {blockPicker(false)}
                  </>
                )}

                {visual && draft ? (
                  <SectionCanvas
                    inspectorRequest={inspectorRequest}
                    appearance={appearance}
                    navigation={navigation}
                    appearanceControls={appearanceControls}
                    templates={
                      <div className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                          {t("startFromTemplateDescription")}
                        </p>
                        <ul className="grid gap-4">
                          {pageTemplates.map((template) => (
                            <li key={template.id}>
                              <TemplateOption
                                closeLabel={common("close")}
                                loading={loading}
                                locale={templateLocale}
                                onApply={() => {
                                  if (blocks.fields.length)
                                    setReplacementTemplate(template);
                                  else void applyTemplate(template);
                                }}
                                previewLabel={t("previewTemplate")}
                                previewTitle={t("previewNamedTemplate", {
                                  name: template.labels[templateLocale].name,
                                })}
                                template={template}
                                thumbnailLabel={t("templateThumbnail", {
                                  name: template.labels[templateLocale].name,
                                })}
                                useLabel={t("useNamedTemplate", {
                                  name: template.labels[templateLocale].name,
                                })}
                              />
                            </li>
                          ))}
                        </ul>
                      </div>
                    }
                    emptyState={
                      <div className="studio-empty-page">
                        <h2>{t("startFromTemplate")}</h2>
                        <p>{t("studio.emptyCanvas")}</p>
                      </div>
                    }
                    library={
                      <>
                        <details className="rounded-lg border p-3">
                          <summary className="cursor-pointer text-sm font-medium">
                            {t("studio.emptyBlock")}
                          </summary>
                          <div className="pt-3">{blockPicker(true)}</div>
                        </details>
                        <SectionLibraryContent
                          onBusyChange={setLoading}
                          compact
                          onAdd={(block) => {
                            if (block.data.image)
                              void listMediaAssets()
                                .then((result) => setAssets(result.items))
                                .catch(() => {});
                            blocks.insert(activeSection + 1, block);
                            setSelectedSection(activeSection + 1);
                          }}
                        />
                      </>
                    }
                    blocks={liveBlocks}
                    onTextChange={(index, path, value) => {
                      if (loading || draftForm.formState.isSubmitting) return;
                      draftForm.setValue(
                        `blocks.${index}.data.${path.join(".")}`,
                        value,
                        { shouldDirty: true, shouldValidate: true },
                      );
                      if (
                        !blockFormSchema.safeParse(
                          draftForm.getValues(`blocks.${index}`),
                        ).success
                      ) {
                        requestAnimationFrame(() =>
                          draftForm.setFocus(
                            `blocks.${index}.data.${path.join(".")}`,
                          ),
                        );
                      }
                    }}
                    blockIds={blocks.fields.map((field) => field.id)}
                    disabled={loading || draftForm.formState.isSubmitting}
                    onMove={(from, to) => {
                      blocks.move(from, to);
                      setSelectedSection(to);
                    }}
                    selected={activeSection}
                    onSelect={setSelectedSection}
                    inspector={
                      blocks.fields.length > 0 ? (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => {
                              blocks.insert(
                                activeSection + 1,
                                structuredClone(
                                  draftForm.getValues(
                                    `blocks.${activeSection}`,
                                  ),
                                ),
                              );
                              setSelectedSection(activeSection + 1);
                            }}
                          >
                            {t("studio.duplicate")}
                          </Button>
                          <SectionLibrary
                            onBusyChange={setLoading}
                            triggerLabel={t("studio.insertAfter")}
                            onAdd={(block) => {
                              if (block.data.image)
                                void listMediaAssets()
                                  .then((result) => setAssets(result.items))
                                  .catch(() => {});
                              blocks.insert(activeSection + 1, block);
                              setSelectedSection(activeSection + 1);
                            }}
                          />
                          <BlockFields
                            assets={assets}
                            form={draftForm}
                            index={activeSection}
                            key={blocks.fields[activeSection].id}
                            type={blocks.fields[activeSection].block_type}
                            isFirst={activeSection === 0}
                            isLast={activeSection === blocks.fields.length - 1}
                            moveUp={() => {
                              blocks.swap(activeSection, activeSection - 1);
                              setSelectedSection(activeSection - 1);
                            }}
                            moveDown={() => {
                              blocks.swap(activeSection, activeSection + 1);
                              setSelectedSection(activeSection + 1);
                            }}
                            onRemove={() => blocks.remove(activeSection)}
                          />
                        </>
                      ) : null
                    }
                  />
                ) : (
                  <>
                    {blocks.fields.map((field, index) => (
                      <BlockFields
                        assets={assets}
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
                  </>
                )}
              </div>
            </fieldset>
          </form>
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(renderedPreview)}
        onOpenChange={(open) => {
          if (!open) setPreview(undefined);
        }}
      >
        <DialogContent
          closeLabel={common("close")}
          className="max-h-[92dvh] overflow-y-auto sm:max-w-[95vw]"
        >
          <DialogTitle>{t("preview")}</DialogTitle>
          <DialogDescription>{t("previewDescription")}</DialogDescription>
          <Card>
            <CardHeader>
              <CardTitle>{t("preview")}</CardTitle>
              <CardDescription>{t("previewDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div
                aria-label={t("previewViewport")}
                className="flex flex-wrap gap-2"
                role="group"
              >
                {(
                  [
                    ["desktop", MonitorIcon],
                    ["tablet", TabletIcon],
                    ["mobile", SmartphoneIcon],
                  ] as const
                ).map(([viewport, Icon]) => (
                  <Button
                    aria-pressed={previewViewport === viewport}
                    key={viewport}
                    onClick={() => setPreviewViewport(viewport)}
                    size="sm"
                    type="button"
                    variant={
                      previewViewport === viewport ? "default" : "outline"
                    }
                  >
                    <Icon aria-hidden="true" />
                    {t(`previewViewport_${viewport}`)}
                  </Button>
                ))}
              </div>
              <div
                className="overflow-x-auto rounded-lg border bg-muted/30 p-3 sm:p-6"
                data-testid="draft-preview"
              >
                <div
                  className="mx-auto min-h-80 rounded-lg border bg-background p-6 shadow-sm transition-[width]"
                  data-testid="draft-preview-viewport"
                  data-viewport={previewViewport}
                  style={{ width: previewWidths[previewViewport] }}
                >
                  {renderedPreview}
                </div>
              </div>
            </CardContent>
          </Card>
        </DialogContent>
      </Dialog>

      <Dialog open={metadataOpen} onOpenChange={setMetadataOpen}>
        <DialogContent
          closeLabel={common("close")}
          className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
        >
          <DialogTitle>{t("metadata")}</DialogTitle>
          <DialogDescription>{t("metadataDescription")}</DialogDescription>
          {metadataProblem && (
            <p role="alert" className="text-sm text-destructive">
              {metadataProblem}
            </p>
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
                  void translationForm.handleSubmit(handleSaveTranslation)(
                    event,
                  );
                }}
              >
                <fieldset
                  disabled={loading || translationForm.formState.isSubmitting}
                  className="space-y-5"
                >
                  <Field>
                    <FieldLabel htmlFor="translation-locale">
                      {t("locale")}
                    </FieldLabel>
                    <Select
                      onValueChange={(nextLocale) => {
                        if (!nextLocale) return;
                        setLocale(nextLocale);
                        setMetadataProblem(undefined);
                        setTranslationConflict(false);
                        translationReceipt.current = undefined;
                        translationForm.reset(
                          translationValues(
                            translations.find(
                              (item) => item.locale === nextLocale,
                            ),
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
                          [
                            "allow_social_description_fallback",
                            "socialDescription",
                          ],
                        ] as const
                      ).map(([name, label]) => (
                        <label
                          className="flex items-center gap-2 text-sm"
                          key={name}
                        >
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
                    <Button
                      disabled={
                        loading ||
                        translationForm.formState.isSubmitting ||
                        translationConflict
                      }
                      type="submit"
                    >
                      <SaveIcon aria-hidden="true" />
                      {t("saveMetadata")}
                    </Button>
                    <Badge variant="outline">
                      {t("versionValue", {
                        version: selectedTranslation?.version ?? 0,
                      })}
                    </Badge>
                    {selectedTranslation?.slug_locked && (
                      <>
                        <Badge variant="secondary">{t("slugLocked")}</Badge>
                        <PageUrlDialog
                          locale={locale}
                          onChanged={reloadTranslations}
                          pageId={page.id}
                          slug={selectedTranslation.slug}
                        />
                      </>
                    )}
                  </div>
                </fieldset>
              </form>
            </CardContent>
          </Card>
        </DialogContent>
      </Dialog>
      <Dialog open={mediaOpen} onOpenChange={setMediaOpen}>
        <DialogContent
          closeLabel={common("close")}
          className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
        >
          <DialogTitle>{t("media")}</DialogTitle>
          <DialogDescription>{t("mediaDescription")}</DialogDescription>
          {mediaProblem && (
            <p role="alert" className="text-sm text-destructive">
              {mediaProblem}
            </p>
          )}
          <fieldset disabled={loading}>
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
          </fieldset>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(replacementTemplate)}
        onOpenChange={(open) => {
          if (!open) setReplacementTemplate(null);
        }}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogTitle>{t("studio.replaceTitle")}</DialogTitle>
          <DialogDescription>
            {t("studio.replaceDescription")}
          </DialogDescription>
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setReplacementTemplate(null)}
            >
              {common("cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => {
                const template = replacementTemplate;
                setReplacementTemplate(null);
                if (template) void applyTemplate(template);
              }}
            >
              {t("studio.replaceConfirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
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

function draftValues(draft: PageDraft): DraftValues {
  return {
    blocks: editableBlocks(draft.blocks),
    media_asset_ids: draft.media_asset_ids,
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
