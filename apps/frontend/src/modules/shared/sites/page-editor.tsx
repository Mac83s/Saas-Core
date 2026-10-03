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
  FormProvider,
  useFieldArray,
  useForm,
  useWatch,
  type SubmitHandler,
} from "react-hook-form";
import {
  EllipsisIcon,
  MonitorIcon,
  EyeIcon,
  HistoryIcon,
  ImageIcon,
  ImagePlusIcon,
  PlusIcon,
  Redo2Icon,
  RefreshCwIcon,
  SaveIcon,
  Settings2Icon,
  SmartphoneIcon,
  TabletIcon,
  Trash2Icon,
  Undo2Icon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  completeMediaUpload,
  getImageGenerationOffer,
  getPageDraft,
  getPageDraftPreview,
  importOwnPageTemplate,
  importPageTemplate,
  restorePageVersion,
  type PageVersionSummary,
  initiateMediaUpload,
  listMediaAssets,
  listPageTranslations,
  savePageDraft,
  savePageTranslation,
  type ImageGenerationOffer,
  type MediaAsset,
  type PageDraft,
  type SiteTemplate,
  type PageSummary,
  type PageTranslation,
} from "@saas-core/api-client";
import {
  availablePageTemplates,
  blockAssetIds,
  renderDraftPreview,
  type PageTemplate,
  type SiteAppearance,
  type NavigationLink,
  type TemplateSwap,
} from "@saas-core/site-blocks";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";
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
  SectionMoveButtons,
  toSiteBlock,
  withUniqueAnchors,
  type BlockFormValues,
  type BlockOption,
} from "./block-form";
import { useCompanyLocales } from "#lib/company-locales";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { privateMediaRenderer } from "./private-media-preview";
import { TemplateSwapDialog } from "./template-swap-dialog";
import {
  pageLookClassName,
  SectionCanvas,
  type SectionCanvasHandle,
} from "./section-canvas";
import {
  PlaceholderBanner,
  templateLeftovers,
  unfilledBySection,
} from "./placeholder-banner";
import { useDraftHistory } from "./draft-history";
import { VersionHistory } from "./version-history";
import { PageEditorContext } from "./page-editor-context";
import { pageTemplatePreview } from "./template-media-preview";
import { SectionLibrary, SectionLibraryContent } from "./section-library";
import { OwnPageTemplates, SaveAsTemplate } from "./own-templates";
import {
  PagePresentationFields,
  type PagePresentation,
} from "./page-presentation-fields";
import { PageUrlDialog } from "./page-url";
import { PageAutomationSwitch, PageTypeField } from "./page-settings";
import { sitesErrorMessage } from "./problem";
import { deployment } from "../../../generated/deployment";

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
  // Only allowlisted values can be chosen; the API validates the contract.
  page_presentation: z.custom<PagePresentation>().nullable(),
});

type DraftValues = z.infer<typeof draftSchema>;
type TranslationValues = z.infer<ReturnType<typeof createTranslationSchema>>;
type PreviewViewport = "desktop" | "tablet" | "mobile";

const previewWidths: Record<PreviewViewport, string> = {
  desktop: "100%",
  tablet: "768px",
  mobile: "390px",
};

export function TemplateOption({
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
  const t = useTranslations("Sites");
  const label = template.labels[locale];
  const style =
    template.pagePresentation && "style" in template.pagePresentation
      ? template.pagePresentation.style
      : undefined;
  const preview = pageTemplatePreview(template, locale);
  const rendered = renderDraftPreview(
    {
      kind: "draft-preview",
      versionId: `template:${template.id}:v${template.version}`,
      blocks: preview.blocks,
      designTokens,
      pagePresentation: template.pagePresentation ?? null,
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
        {(template.conversion || style) && (
          <p className="flex flex-wrap gap-1.5">
            {template.conversion && (
              <Badge variant="secondary">
                {t("templateGoal", {
                  goal: t(`conversionGoals.${template.conversion.goal}`),
                })}
              </Badge>
            )}
            {style && (
              <Badge variant="outline">
                {t("templateStyle", {
                  style: t(`pagePresentation.styles.${style}.name`),
                })}
              </Badge>
            )}
          </p>
        )}
      </CardHeader>
      <CardContent className="grid gap-2">
        <Dialog>
          <DialogTrigger
            render={
              <Button
                className="h-auto min-h-10 w-full whitespace-normal py-2"
                type="button"
                variant="outline"
              />
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
        {/* The studio rail is 300 px: a long template name wraps. */}
        <Button
          aria-label={useLabel}
          className="h-auto min-h-10 whitespace-normal py-2"
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

/**
 * The offer's address exists only where the deployment composes image
 * generation: elsewhere asking for it is a 404 in the console (UX-041).
 */
const generatesImages = () =>
  (deployment.modules as readonly string[]).includes("shared.image-generation");

/** Where a picture sits in a section's data, as the form addresses it:
 *  `["image", "asset_id"]`, `["images", "0", "asset_id"]` or a figure inside
 *  rich text. The first match: a section rarely shows one photo twice. */
function assetPath(value: unknown, assetId: string): string[] | undefined {
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      const found = assetPath(item, assetId);
      if (found) return [String(index), ...found];
    }
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (key === "asset_id" && item === assetId) return [key];
      const found = assetPath(item, assetId);
      if (found) return [key, ...found];
    }
  }
  return undefined;
}

export function PageEditor({
  onChanged,
  onExitStateChange,
  pagesPanel,
  appearance,
  appearanceControls,
  savedAppearance,
  navigation,
  page,
  previewOnOpen = false,
  languageSwitch,
  leading,
}: {
  /** The studio's way back and its dialog title, first in the top bar. */
  leading?: ReactNode;
  onChanged: () => Promise<void>;
  onExitStateChange?: (state: { dirty: boolean; busy: boolean }) => void;
  /** The site's pages in the studio's left rail (F3-Z3). */
  pagesPanel?: ReactNode;
  page: PageSummary;
  appearance?: SiteAppearance;
  savedAppearance?: SiteAppearance;
  navigation?: readonly NavigationLink[];
  appearanceControls?: ReactNode;
  /** The list's "Preview": the draft opens in the preview once loaded. */
  previewOnOpen?: boolean;
  /** The page's language (TL15, development-51): beside „Zapisz” on every
   *  screen; the toolbar keeps its place either way. */
  languageSwitch?: ReactNode;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const interfaceLocale = useLocale();
  // Read once: a later change of the prop must not reopen the preview.
  const previewPending = useRef(previewOnOpen);
  const [draft, setDraft] = useState<PageDraft>();
  const [translations, setTranslations] = useState<PageTranslation[]>([]);
  const [locale, setLocale] = useState("pl");
  const [baseLocale, setBaseLocale] = useState("pl");
  const companyLocaleOptions = useCompanyLocales(["pl", "en"]);
  // The company's languages, plus the page's own while it still has one the
  // company has switched off since.
  const localeOptions = [
    ...companyLocaleOptions,
    ...[...new Set([baseLocale, locale])]
      .filter(
        (code) => !companyLocaleOptions.some((item) => item.code === code),
      )
      .map((code) => ({ code, name: code.toUpperCase() })),
  ];
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  // Read once per editor: a 403 or an unavailable offer hides the AI button.
  const [imageGeneration, setImageGeneration] =
    useState<ImageGenerationOffer | null>(null);
  useEffect(() => {
    if (!generatesImages()) return;
    let mounted = true;
    getImageGenerationOffer()
      .then((offer) => {
        if (mounted) setImageGeneration(offer);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);
  const [selectedBlock, setSelectedBlock] = useState<BlockOption | null>(null);
  const [assetOption, setAssetOption] = useState<MediaAsset | null>(null);
  const [preview, setPreview] = useState<PageDraft>();
  const [previewViewport, setPreviewViewport] =
    useState<PreviewViewport>("desktop");
  const [canvasViewport, setCanvasViewport] =
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
  const restoreReceipt = useRef<MutationReceipt | undefined>(undefined);
  // A whole page from the server redraws the canvas (SectionCanvas `revision`).
  const [canvasRevision, setCanvasRevision] = useState(0);
  // "Przywrócono wersję …": said once after a restore, until the next edit.
  const [restoredNotice, setRestoredNotice] = useState<string>();

  const draftForm = useForm<DraftValues>({
    resolver: zodResolver(draftSchema),
    defaultValues: { blocks: [], media_asset_ids: [], page_presentation: null },
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
  const unfilled = useMemo(() => unfilledBySection(liveBlocks), [liveBlocks]);
  const leftovers = useMemo(() => templateLeftovers(liveBlocks), [liveBlocks]);
  const canvas = useRef<SectionCanvasHandle>(null);
  const pagePresentation = useWatch({
    control: draftForm.control,
    name: "page_presentation",
  });
  const history = useDraftHistory(draftForm);
  const [visual, setVisual] = useState(true);
  const [mediaOpen, setMediaOpen] = useState(false);
  const [mediaProblem, setMediaProblem] = useState<string>();
  const [metadataProblem, setMetadataProblem] = useState<string>();
  const [inspectorRequest, setInspectorRequest] = useState(0);
  // The canvas's "+" and "Zmień zdjęcie": where to insert, which field to open.
  const [insertAt, setInsertAt] = useState<number | null>(null);
  const [focusField, setFocusField] = useState<{
    name: string;
    request: number;
  }>();
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // The template chosen for a page with content, and the sections the swap
  // preview was drawn from — the same ones the import then sends (F4-C).
  const [replacement, setReplacement] = useState<{
    template: PageTemplate | SiteTemplate;
    blocks: BlockFormValues[];
  } | null>(null);
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

  /** Saves the draft as it stands in the form; the caller takes the answer. */
  const persistDraft = useCallback(
    async (values: DraftValues, current: PageDraft): Promise<PageDraft> => {
      const input = {
        expected_version: current.version,
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
        // Absent keeps the stored look, so a page nobody restyled sends
        // nothing; `null` is an explicit return to the site's look.
        ...(samePagePresentation(
          values.page_presentation,
          (current.page_presentation ?? null) as PagePresentation | null,
        )
          ? {}
          : { page_presentation: values.page_presentation }),
      };
      const saved = await savePageDraft(
        page.id,
        input,
        mutationKey(draftReceipt, `draft-${page.id}`, input),
      );
      draftReceipt.current = undefined;
      return saved;
    },
    [page.id],
  );

  const applyTemplate = useCallback(
    async (
      template: PageTemplate | SiteTemplate,
      swap?: { plan: TemplateSwap | null; blocks: BlockFormValues[] },
    ) => {
      if (!draft) return;
      setLoading(true);
      setProblem(undefined);
      setDraftConflict(false);
      try {
        let expected = draft.version;
        // Replacing a page with content first keeps what is on screen as a
        // version of its own, so whatever the swap leaves out stays in the
        // history — unsaved edits included.
        if (swap && draftForm.formState.isDirty) {
          const saved = await persistDraft(
            { ...draftForm.getValues(), blocks: swap.blocks },
            draft,
          );
          setDraft(saved);
          expected = saved.version;
        }
        const composition = swap?.plan
          ? {
              ...(swap.plan.kept.length ? { kept: [...swap.plan.kept] } : {}),
              ...(swap.plan.appended.length
                ? { appended: [...swap.plan.appended] }
                : {}),
            }
          : {};
        let imported: PageDraft;
        if ("labels" in template) {
          const input = {
            expected_version: expected,
            template_id: template.id,
            template_version: template.version,
            locale: templateLocale,
            ...composition,
          } as const;
          imported = await importPageTemplate(
            page.id,
            input,
            mutationKey(templateReceipt, `template-${page.id}`, input),
          );
        } else {
          // The organization's own page (F4-B): its content, as saved.
          const input = {
            expected_version: expected,
            template_id: template.id,
            template_version: template.version.number,
            ...composition,
          };
          imported = await importOwnPageTemplate(
            page.id,
            input,
            mutationKey(templateReceipt, `own-template-${page.id}`, input),
          );
        }
        templateReceipt.current = undefined;
        setDraft(imported);
        const values = draftValues(imported);
        // A recipe's anchors are unique already; this keeps the rule in one
        // place should an import ever merge with existing sections.
        draftForm.reset({
          ...values,
          blocks: withUniqueAnchors(values.blocks, []),
        });
        setCanvasRevision((revision) => revision + 1);
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
    [draft, draftForm, onChanged, page.id, persistDraft, t, templateLocale],
  );

  /** A section turned into another type (F4-C): one undo step, its anchors
   *  kept unique against the rest of the page. */
  function replaceSection(index: number, block: BlockFormValues) {
    const others = draftForm
      .getValues("blocks")
      .filter((_, position) => position !== index);
    blocks.update(index, withUniqueAnchors([block], others)[0]!);
  }

  /** A new version with an earlier version's content (F4-A); the form and its
   *  history start over from it, like after a template import. */
  async function restoreVersion(version: PageVersionSummary) {
    if (!draft) return;
    const input = { expected_version: draft.version };
    setLoading(true);
    setProblem(undefined);
    setDraftConflict(false);
    try {
      const restored = await restorePageVersion(
        page.id,
        version.id,
        input,
        mutationKey(restoreReceipt, `restore-${page.id}-${version.id}`, input),
      );
      restoreReceipt.current = undefined;
      setDraft(restored);
      draftForm.reset(draftValues(restored));
      setCanvasRevision((revision) => revision + 1);
      setPreview(undefined);
      setRestoredNotice(
        t("versions.restored", {
          from: version.number,
          number: restored.version,
        }),
      );
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
  }

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
      .then(async ([loadedDraft, loadedTranslations, loadedAssets]) => {
        if (!mounted) return;
        applyLoadedData(
          loadedDraft,
          loadedTranslations.items,
          loadedTranslations.default_locale,
        );
        setAssets(loadedAssets.items);
        if (previewPending.current && loadedDraft.draft_id) {
          previewPending.current = false;
          const shown = await getPageDraftPreview(
            page.id,
            loadedDraft.draft_id,
          );
          if (mounted) setPreview(shown);
        }
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
      setCanvasRevision((revision) => revision + 1);
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
    try {
      const saved = await persistDraft(values, draft);
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
    // No language borrows the source's title or description any more: a
    // version with its own body has its own words (TL15).
    const input = {
      ...values,
      expected_version: selectedTranslation?.version ?? 0,
      allow_title_fallback: false,
      allow_description_fallback: false,
      allow_social_title_fallback: false,
      allow_social_description_fallback: false,
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

  /** The saved draft, or — from the history — any earlier version. */
  async function showPreview(versionId?: string) {
    const target = versionId ?? draft?.draft_id;
    if (!target) return;
    setLoading(true);
    setProblem(undefined);
    try {
      setPreview(await getPageDraftPreview(page.id, target));
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
        // The saved version's own look, like its blocks.
        pagePresentation: (preview.page_presentation ??
          null) as PagePresentation | null,
        blocks: preview.blocks.map(toSiteBlock),
        designTokens,
      },
      registry,
      privateMediaRenderer(
        // The badge only where published pages show it (operator switch);
        // unknown when there is no offer, so shown as by default.
        imageGeneration?.badge_visible === false
          ? new Set<string>()
          : new Set(
              assets
                .filter((asset) => asset.ai_origin === "generated")
                .map((asset) => asset.id),
            ),
        locale === "en" ? "en" : "pl",
      ),
    );
  }, [preview, savedAppearance, assets, locale, imageGeneration]);

  /** Every section entering the page from the library goes through here:
   *  its photos refresh the media list and its heading anchors are renamed
   *  against the page's (the API refuses a duplicate anchor). */
  const addSection = (block: BlockFormValues, position: number) => {
    if (blockAssetIds(block.data).length > 0)
      void listMediaAssets()
        .then((result) => setAssets(result.items))
        .catch(() => {});
    const [unique] = withUniqueAnchors([block], draftForm.getValues("blocks"));
    blocks.insert(position, unique);
    setSelectedSection(position);
  };
  const refreshAssets = () =>
    void listMediaAssets()
      .then((result) => setAssets(result.items))
      .catch(() => {});
  const pageLook = (
    <PagePresentationFields
      value={pagePresentation}
      onChange={(value) =>
        draftForm.setValue("page_presentation", value, { shouldDirty: true })
      }
    />
  );

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
      <Card className="studio-editor-main">
        <CardContent className="studio-editor-content">
          <FormProvider {...draftForm}>
            <PageEditorContext
              value={{
                undo: history.undo,
                redo: history.redo,
                look: pageLookClassName(appearance, pagePresentation),
                imageGeneration,
              }}
            >
              <form
                className="studio-editor-form"
                onKeyDown={(event) => {
                  // The page's undo from anywhere in the studio; a text field
                  // keeps its own, and the rich-text editor routes to this one.
                  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
                  if (loading || draftForm.formState.isSubmitting) return;
                  const target = event.target as HTMLElement;
                  if (
                    target.closest(
                      'input, textarea, select, [contenteditable="true"]',
                    )
                  )
                    return;
                  const key = event.key.toLowerCase();
                  if (key === "z" && !event.shiftKey) {
                    event.preventDefault();
                    history.undo();
                  } else if ((key === "z" && event.shiftKey) || key === "y") {
                    event.preventDefault();
                    history.redo();
                  }
                }}
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
                <fieldset
                  disabled={loading || draftForm.formState.isSubmitting}
                  className="studio-editor-fieldset"
                >
                  {/* One row: the page on the left, the device in the middle,
                      saving on the right, the rest under „Więcej”. A phone
                      keeps the page over save, preview and „…” (UX-039). */}
                  <div className="studio-toolbar studio-topbar">
                    {leading}
                    <div className="studio-topbar-page">
                      <p className="truncate text-sm font-semibold">
                        {page.name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {t("studio.draftVersion", {
                          version: draft?.version ?? 0,
                        })}
                      </p>
                    </div>
                    <span
                      aria-hidden="true"
                      className="studio-topbar-divider hidden sm:block"
                    />
                    <div
                      aria-label={t("studio.mode")}
                      className="studio-segmented inline-flex max-sm:hidden"
                      role="group"
                    >
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="pointer-fine:h-7"
                        aria-pressed={visual}
                        onClick={() => setVisual(true)}
                      >
                        {t("studio.visual")}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="pointer-fine:h-7"
                        aria-pressed={!visual}
                        onClick={() => setVisual(false)}
                      >
                        {t("studio.forms")}
                      </Button>
                    </div>
                    <div className="flex gap-0.5 max-sm:hidden">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="pointer-fine:size-8"
                        aria-label={t("studio.undo")}
                        title={t("studio.undo")}
                        disabled={!history.canUndo}
                        onClick={history.undo}
                      >
                        <Undo2Icon aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="pointer-fine:size-8"
                        aria-label={t("studio.redo")}
                        title={t("studio.redo")}
                        disabled={!history.canRedo}
                        onClick={history.redo}
                      >
                        <Redo2Icon aria-hidden="true" />
                      </Button>
                    </div>
                    {/* A phone already is the phone view (UX-039); the forms
                        have no canvas to resize. */}
                    <div className="studio-topbar-center hidden sm:flex">
                      {visual && (
                        <div
                          aria-label={t("previewViewport")}
                          className="studio-segmented inline-flex"
                          role="group"
                        >
                          {(
                            [
                              ["desktop", MonitorIcon],
                              ["tablet", TabletIcon],
                              ["mobile", SmartphoneIcon],
                            ] as const
                          ).map(([value, Icon]) => (
                            <Button
                              key={value}
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              className="pointer-fine:h-7 pointer-fine:w-9"
                              aria-label={t(`previewViewport_${value}`)}
                              title={t(`previewViewport_${value}`)}
                              aria-pressed={canvasViewport === value}
                              onClick={() => setCanvasViewport(value)}
                            >
                              <Icon aria-hidden="true" />
                            </Button>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="studio-save-actions">
                      {languageSwitch}
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          aria-label={t("studio.more")}
                          title={t("studio.more")}
                          className={buttonVariants({
                            variant: "outline",
                            size: "icon-sm",
                            className: "pointer-fine:size-8",
                          })}
                        >
                          <EllipsisIcon aria-hidden="true" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {/* What a wide screen shows in the row. */}
                          <DropdownMenuRadioGroup
                            className="sm:hidden"
                            onValueChange={(value) =>
                              setVisual(value === "visual")
                            }
                            value={visual ? "visual" : "forms"}
                          >
                            <DropdownMenuRadioItem value="visual">
                              {t("studio.visual")}
                            </DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value="forms">
                              {t("studio.forms")}
                            </DropdownMenuRadioItem>
                          </DropdownMenuRadioGroup>
                          <DropdownMenuGroup className="sm:hidden">
                            <DropdownMenuItem
                              disabled={!history.canUndo}
                              onClick={history.undo}
                            >
                              <Undo2Icon aria-hidden="true" />
                              {t("studio.undo")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={!history.canRedo}
                              onClick={history.redo}
                            >
                              <Redo2Icon aria-hidden="true" />
                              {t("studio.redo")}
                            </DropdownMenuItem>
                          </DropdownMenuGroup>
                          <DropdownMenuSeparator className="sm:hidden" />
                          <DropdownMenuItem onClick={() => setMediaOpen(true)}>
                            <ImageIcon aria-hidden="true" />
                            {t("media")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => setMetadataOpen(true)}
                          >
                            <Settings2Icon aria-hidden="true" />
                            {t("studio.pageSettings")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={loading || !draft?.draft_id}
                            onClick={() => setHistoryOpen(true)}
                          >
                            <HistoryIcon aria-hidden="true" />
                            {t("versions.open")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button
                        disabled={loading || !draft?.draft_id}
                        onClick={() => void showPreview()}
                        type="button"
                        variant="outline"
                        size="sm"
                        className="pointer-fine:h-8"
                        aria-label={t("preview")}
                        title={t("preview")}
                      >
                        <EyeIcon aria-hidden="true" />
                        <span className="max-sm:hidden">{t("preview")}</span>
                      </Button>
                      <Button
                        disabled={loading || draftConflict}
                        type="submit"
                        size="sm"
                        className="pointer-fine:h-8"
                      >
                        <SaveIcon aria-hidden="true" />
                        {t("studio.save")}
                      </Button>
                    </div>
                    <VersionHistory
                      pageId={page.id}
                      dirty={draftForm.formState.isDirty}
                      disabled={loading || !draft?.draft_id}
                      onPreview={(version) => void showPreview(version.id)}
                      onRestore={restoreVersion}
                      open={historyOpen}
                      onOpenChange={setHistoryOpen}
                    />
                  </div>
                  {/* Under the top bar, so the bar stays where it is. */}
                  {(problem ||
                    draftConflict ||
                    (restoredNotice && !draftForm.formState.isDirty)) && (
                    <div className="studio-notices">
                      {problem && (
                        <div
                          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
                          role="alert"
                        >
                          {problem}
                        </div>
                      )}
                      {restoredNotice && !draftForm.formState.isDirty && (
                        <p
                          className="rounded-lg border bg-muted/40 p-3 text-sm"
                          role="status"
                        >
                          {restoredNotice}
                        </p>
                      )}
                      {draftConflict && (
                        <div
                          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4"
                          role="alert"
                        >
                          <p className="text-sm text-destructive">
                            {t("draftConflict")}
                          </p>
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
                    </div>
                  )}
                  <PlaceholderBanner
                    blocks={liveBlocks}
                    counts={unfilled}
                    leftovers={leftovers}
                    onChoose={(index) => {
                      if (canvas.current) canvas.current.choose(index);
                      else {
                        setVisual(true);
                        setSelectedSection(index);
                      }
                    }}
                  />
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
                        <details className="rounded-lg border p-3">
                          <summary className="cursor-pointer font-semibold">
                            {t("pagePresentation.title")}
                          </summary>
                          <div className="pt-3">{pageLook}</div>
                        </details>
                        <SectionLibrary
                          onBusyChange={setLoading}
                          onAdd={(block) =>
                            addSection(block, blocks.fields.length)
                          }
                        />
                        {blockPicker(false)}
                      </>
                    )}

                    {visual && draft ? (
                      <>
                        <SectionLibrary
                          open={insertAt !== null}
                          onOpenChange={(open) => {
                            if (!open) setInsertAt(null);
                          }}
                          onBusyChange={setLoading}
                          onAdd={(block) => {
                            if (insertAt !== null) addSection(block, insertAt);
                          }}
                        />
                        <SectionCanvas
                          ref={canvas}
                          viewport={canvasViewport}
                          revision={canvasRevision}
                          unfilled={unfilled}
                          inspectorActions={
                            blocks.fields.length > 0 ? (
                              <SectionMoveButtons
                                isFirst={activeSection === 0}
                                isLast={
                                  activeSection === blocks.fields.length - 1
                                }
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
                            ) : null
                          }
                          inspectorRequest={inspectorRequest}
                          appearance={appearance}
                          navigation={navigation}
                          pagePresentation={pagePresentation}
                          pagesPanel={pagesPanel}
                          appearanceControls={
                            <div className="space-y-6">
                              {appearanceControls}
                              {pageLook}
                            </div>
                          }
                          templates={
                            <div className="space-y-4">
                              <p className="text-sm text-muted-foreground">
                                {t("startFromTemplateDescription")}
                              </p>
                              <SaveAsTemplate
                                kind="page"
                                triggerLabel={t("ownTemplates.savePage")}
                                disabled={loading || blocks.fields.length === 0}
                                blocks={() => draftForm.getValues("blocks")}
                                pagePresentation={() =>
                                  draftForm.getValues("page_presentation")
                                }
                                sourcePageId={page.id}
                              />
                              <OwnPageTemplates
                                disabled={loading}
                                onUse={(template) => {
                                  if (blocks.fields.length)
                                    setReplacement({
                                      template,
                                      blocks: draftForm.getValues("blocks"),
                                    });
                                  else void applyTemplate(template);
                                }}
                              />
                              <h3 className="text-sm font-semibold">
                                {t("ownTemplates.readyGroup")}
                              </h3>
                              <ul className="grid gap-4">
                                {pageTemplates.map((template) => (
                                  <li key={template.id}>
                                    <TemplateOption
                                      closeLabel={common("close")}
                                      loading={loading}
                                      locale={templateLocale}
                                      onApply={() => {
                                        if (blocks.fields.length)
                                          setReplacement({
                                            template,
                                            blocks:
                                              draftForm.getValues("blocks"),
                                          });
                                        else void applyTemplate(template);
                                      }}
                                      previewLabel={t("previewTemplate")}
                                      previewTitle={t("previewNamedTemplate", {
                                        name: template.labels[templateLocale]
                                          .name,
                                      })}
                                      template={template}
                                      thumbnailLabel={t("templateThumbnail", {
                                        name: template.labels[templateLocale]
                                          .name,
                                      })}
                                      useLabel={t("useNamedTemplate", {
                                        name: template.labels[templateLocale]
                                          .name,
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
                                onAdd={(block) =>
                                  addSection(block, activeSection + 1)
                                }
                              />
                            </>
                          }
                          blocks={liveBlocks}
                          onTextChange={(index, path, value) => {
                            if (loading || draftForm.formState.isSubmitting)
                              return;
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
                          onInsertAt={setInsertAt}
                          focusField={focusField}
                          onChangeImage={(index, assetId) => {
                            const path = assetPath(
                              draftForm.getValues(`blocks.${index}.data`),
                              assetId,
                            );
                            if (!path) return;
                            setFocusField((previous) => ({
                              name: `blocks.${index}.data.${path.join(".")}`,
                              request: (previous?.request ?? 0) + 1,
                            }));
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
                                    const current =
                                      draftForm.getValues("blocks");
                                    // The copy's headings get anchors of their own.
                                    const [copy] = withUniqueAnchors(
                                      [structuredClone(current[activeSection])],
                                      current,
                                    );
                                    blocks.insert(activeSection + 1, copy);
                                    setSelectedSection(activeSection + 1);
                                  }}
                                >
                                  {t("studio.duplicate")}
                                </Button>
                                <SaveAsTemplate
                                  kind="section"
                                  triggerLabel={t("ownTemplates.saveSection")}
                                  disabled={loading}
                                  blocks={() => [
                                    draftForm.getValues(
                                      `blocks.${activeSection}`,
                                    ),
                                  ]}
                                  sourcePageId={page.id}
                                />
                                <SectionLibrary
                                  onBusyChange={setLoading}
                                  triggerLabel={t("studio.insertAfter")}
                                  onAdd={(block) =>
                                    addSection(block, activeSection + 1)
                                  }
                                />
                                <BlockFields
                                  assets={assets}
                                  form={draftForm}
                                  index={activeSection}
                                  key={blocks.fields[activeSection].id}
                                  titled
                                  type={blocks.fields[activeSection].block_type}
                                  isFirst={activeSection === 0}
                                  isLast={
                                    activeSection === blocks.fields.length - 1
                                  }
                                  onMediaUploaded={refreshAssets}
                                  moveUp={() => {
                                    blocks.swap(
                                      activeSection,
                                      activeSection - 1,
                                    );
                                    setSelectedSection(activeSection - 1);
                                  }}
                                  moveDown={() => {
                                    blocks.swap(
                                      activeSection,
                                      activeSection + 1,
                                    );
                                    setSelectedSection(activeSection + 1);
                                  }}
                                  onRemove={() => blocks.remove(activeSection)}
                                  onReplace={(block) =>
                                    replaceSection(activeSection, block)
                                  }
                                />
                              </>
                            ) : null
                          }
                        />
                      </>
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
                            onMediaUploaded={refreshAssets}
                            onRemove={() => blocks.remove(index)}
                            onReplace={(block) => replaceSection(index, block)}
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
            </PageEditorContext>
          </FormProvider>
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
          <DialogTitle>
            {preview && preview.draft_id !== draft?.draft_id
              ? t("versions.previewNamed", { number: preview.version })
              : t("preview")}
          </DialogTitle>
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
          {/* The page's own settings, beside its address and metadata. */}
          <Card>
            <CardHeader>
              <CardTitle>{t("pageKindTitle")}</CardTitle>
              <CardDescription>{t("pageSettingsDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <PageTypeField onChanged={() => void onChanged()} page={page} />
              <PageAutomationSwitch
                onChanged={() => void onChanged()}
                page={page}
              />
            </CardContent>
          </Card>
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
                        {localeOptions.map((item) => (
                          <SelectItem key={item.code} value={item.code}>
                            {item.name}
                          </SelectItem>
                        ))}
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
      <TemplateSwapDialog
        blocks={replacement?.blocks ?? []}
        disabled={loading}
        locale={templateLocale}
        onCancel={() => setReplacement(null)}
        onConfirm={(plan) => {
          const chosen = replacement;
          setReplacement(null);
          if (chosen)
            void applyTemplate(chosen.template, {
              plan,
              blocks: chosen.blocks,
            });
        }}
        template={replacement?.template ?? null}
        unsaved={draftForm.formState.isDirty}
      />
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
    page_presentation: (draft.page_presentation ??
      null) as PagePresentation | null,
  };
}

/** Key order is not meaning: the API may return keys in another order. */
function samePagePresentation(
  left: PagePresentation | null,
  right: PagePresentation | null,
): boolean {
  if (left === null || right === null) return left === right;
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].every(
    (key) =>
      left[key as keyof PagePresentation] ===
      right[key as keyof PagePresentation],
  );
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
