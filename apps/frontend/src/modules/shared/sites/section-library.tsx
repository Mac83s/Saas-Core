"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  EyeIcon,
  MonitorIcon,
  PlusIcon,
  SearchIcon,
  SmartphoneIcon,
} from "lucide-react";
import {
  applySampleMedia,
  availableSectionTemplates,
  sampleMediaOf,
  sectionIndustries,
  sectionTemplateBlock,
  renderDraftPreview,
  type SectionTemplate,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Input } from "@saas-core/ui/components/input";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import {
  ApiProblemError,
  materializeTemplatePhoto,
} from "@saas-core/api-client";
import { product } from "../../../product";
import { sectionPreview } from "./template-media-preview";
import {
  registry,
  editableBlocks,
  useSectionTypeName,
  type BlockFormValues,
} from "./block-form";
import { OwnSectionTemplates } from "./own-templates";

/** Library order and category filter: the families interleave in this order. */
const BLOCK_TYPES = [
  "hero",
  "feature_list",
  "faq",
  "contact",
  "contact_form",
  "link_list",
  "separator",
  "rich_text",
  "quote",
  "product",
  "gallery",
] as const;

const tokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

/** A dialog with its own trigger button, or — given `open` — one the caller
 *  opens (the canvas's "+" between sections) and closes on `onOpenChange`. */
export function SectionLibrary({
  onAdd,
  triggerLabel,
  onBusyChange,
  open: openProp,
  onOpenChange,
}: {
  onAdd: (block: BlockFormValues) => void;
  triggerLabel?: string;
  onBusyChange?: (busy: boolean) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("Sites.sectionLibrary");
  const common = useTranslations("Common");
  const [ownOpen, setOwnOpen] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : ownOpen;
  const setOpen = (next: boolean) =>
    controlled ? onOpenChange?.(next) : setOwnOpen(next);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) setOpen(next);
      }}
    >
      {controlled ? null : (
        <DialogTrigger render={<Button type="button" variant="outline" />}>
          {triggerLabel ?? t("open")}
        </DialogTrigger>
      )}
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-6xl"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <SectionLibraryContent
          onBusyChange={(next) => {
            setBusy(next);
            onBusyChange?.(next);
          }}
          onAdd={(block) => {
            onAdd(block);
            setOpen(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

/** The same catalog powers the persistent studio rail and contextual dialog. */
export function SectionLibraryContent({
  onAdd,
  compact = false,
  onBusyChange,
}: {
  onAdd: (block: BlockFormValues) => void;
  compact?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const t = useTranslations("Sites.sectionLibrary");
  const typeName = useSectionTypeName();
  const common = useTranslations("Common");
  const id = useId();
  const locale = useLocale() === "en" ? "en" : "pl";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<false | "photoError" | "scannerBusy">(
    false,
  );
  const [limit, setLimit] = useState(12);
  const pending = useRef(false);
  const receipts = useRef(new Map<string, string>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [query, setQuery] = useState("");
  // The product's trade first (decision 4a, 24.09); an id the catalogue does
  // not know would filter nothing, so it falls back to all.
  const [industry, setIndustry] = useState(() =>
    sectionIndustries().some((item) => item.id === product.siteIndustry)
      ? (product.siteIndustry ?? "")
      : "",
  );
  const [blockType, setBlockType] = useState("");
  const [selected, setSelected] = useState<SectionTemplate | null>(null);
  const [mobile, setMobile] = useState(false);
  const previewTrigger = useRef<HTMLButtonElement>(null);
  // Every category's count follows the search and the trade; the chosen
  // category narrows the list.
  const matching = useMemo(
    () =>
      availableSectionTemplates(registry, {
        entitlements: ["sites.enabled"],
        modules: ["shared.sites"],
        industry,
        blockType: "",
      }).filter((template) => {
        const search = query.trim().toLocaleLowerCase(locale);
        if (!search) return true;
        const labels = template.labels[locale];
        return `${labels.name} ${labels.description} ${labels.usage}`
          .toLocaleLowerCase(locale)
          .includes(search);
      }),
    [industry, query, locale],
  );
  const templates = useMemo(
    () =>
      blockType
        ? matching.filter((template) => template.blockType === blockType)
        : matching,
    [matching, blockType],
  );
  const categories = useMemo(
    () =>
      [
        { value: "", count: matching.length },
        ...BLOCK_TYPES.map((name) => ({
          value: `core.${name}`,
          count: matching.filter((item) => item.blockType === `core.${name}`)
            .length,
        })),
      ].filter(
        // An empty category is no choice, unless it is the chosen one.
        (category) =>
          category.count > 0 ||
          category.value === "" ||
          category.value === blockType,
      ),
    [matching, blockType],
  );
  const ordered = useMemo(() => {
    const groups = BLOCK_TYPES.map((type) =>
      templates.filter((item) => item.blockType === `core.${type}`),
    );
    const mixed = Array.from(
      { length: Math.max(...groups.map((group) => group.length), 0) },
      (_, index) =>
        groups.flatMap((group) => (group[index] ? [group[index]] : [])),
    ).flat();
    return industry
      ? [
          ...mixed.filter((item) => item.kind === "industry"),
          ...mixed.filter((item) => item.kind === "default"),
        ]
      : mixed;
  }, [templates, industry]);
  const choose = async (template: SectionTemplate) => {
    if (pending.current) return;
    setError(false);
    const seeded = sectionTemplateBlock(template, locale, registry);
    const photos = [...new Set(sampleMediaOf(template).map((item) => item.id))];
    if (photos.length === 0) {
      onAdd(editableBlocks([seeded])[0]);
      setSelected(null);
      return;
    }
    pending.current = true;
    setBusy(true);
    onBusyChange?.(true);
    try {
      // One asset per sample photo; its receipt makes a retry, or another
      // section with the same photo, reuse that asset.
      const assets = new Map<string, string>();
      for (const photo of photos) {
        if (!receipts.current.has(photo))
          receipts.current.set(
            photo,
            `template-photo-${globalThis.crypto.randomUUID()}`,
          );
        const result = await materializeTemplatePhoto(
          photo,
          receipts.current.get(photo)!,
        );
        if (!mounted.current) return;
        assets.set(photo, result.asset_id);
      }
      // Each photo goes where the template says (a product's or a gallery's
      // item, not only `image`).
      const bound = applySampleMedia(
        seeded,
        template,
        (photo) => assets.get(photo)!,
        locale,
      );
      registry.validate(bound);
      onAdd(editableBlocks([bound])[0]);
      setSelected(null);
    } catch (failure) {
      if (mounted.current)
        setError(
          failure instanceof ApiProblemError &&
            failure.problem.code === "media_scanner_unavailable"
            ? "scannerBusy"
            : "photoError",
        );
    } finally {
      pending.current = false;
      if (mounted.current) {
        setBusy(false);
        onBusyChange?.(false);
      }
    }
  };
  const renderPreview = (template: SectionTemplate) => {
    const preview = sectionPreview(template, locale);
    return renderDraftPreview(
      {
        kind: "draft-preview",
        versionId: template.id,
        blocks: preview.blocks,
        designTokens: tokens,
      },
      registry,
      preview.imageRenderer,
    );
  };
  const feedback = (
    <>
      {busy && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm">
          {t("preparingPhoto")}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {t(error)}
        </p>
      )}
    </>
  );
  const details = (
    <details className="rounded-lg border px-3 py-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium text-foreground">
        {t("details")}
      </summary>
      <div className="space-y-2 pt-2 leading-relaxed">
        <p>{t("universalIncluded")}</p>
        <p>{t("samplePhotos")}</p>
      </div>
    </details>
  );
  const Name = compact ? "h4" : "h3";
  const preview = (template: SectionTemplate, trigger: HTMLButtonElement) => {
    previewTrigger.current = trigger;
    setSelected(template);
  };
  return (
    <div className={`min-w-0 ${compact ? "space-y-3" : "space-y-4"}`}>
      <div className="space-y-2.5">
        <Field>
          <FieldLabel htmlFor={`${id}-search`} className="sr-only">
            {t("search")}
          </FieldLabel>
          <div className="relative">
            <SearchIcon
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id={`${id}-search`}
              type="search"
              className="pl-9 pointer-fine:h-9"
              placeholder={t("searchPlaceholder")}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setLimit(12);
              }}
            />
          </div>
        </Field>
        {/* One tap per category, its count beside it (Kreator stron). */}
        <div className="studio-chips" role="group" aria-label={t("category")}>
          {categories.map((category) => (
            <button
              key={category.value || "all"}
              type="button"
              aria-pressed={blockType === category.value}
              title={category.value ? undefined : t("allCategories")}
              onClick={() => {
                setBlockType(category.value);
                setLimit(12);
                setSelected(null);
              }}
            >
              {/* A kind of section has one name: the outline's and the
                  inspector's (`useSectionTypeName`). */}
              {category.value ? typeName(category.value) : t("allShort")}
              <span aria-hidden="true">{category.count}</span>
            </button>
          ))}
        </div>
        {/* The trade stays a choice of its own (owner's answer 1a, 03.10). */}
        <Field>
          <FieldLabel htmlFor={`${id}-industry`} className="sr-only">
            {t("industry")}
          </FieldLabel>
          <NativeSelect
            id={`${id}-industry`}
            className="pointer-fine:h-9"
            value={industry}
            onChange={(event) => {
              setIndustry(event.target.value);
              setLimit(12);
              setSelected(null);
            }}
          >
            <option value="">{t("allIndustries")}</option>
            {sectionIndustries().map((item) => (
              <option key={item.id} value={item.id}>
                {item.labels[locale]}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <span
        aria-live="polite"
        className={compact ? "sr-only" : "block text-xs text-muted-foreground"}
      >
        {t("results", { count: templates.length })}
      </span>
      {!compact && details}
      {!selected && feedback}
      <OwnSectionTemplates
        query={query}
        blockType={blockType}
        compact={compact}
        disabled={busy}
        onAdd={onAdd}
      />
      <div
        className={
          compact
            ? "studio-library-list"
            : "grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        }
      >
        {ordered.slice(0, limit).map((template) =>
          compact ? (
            <article key={template.id} className="studio-library-row">
              {/* The whole row adds for a pointer; the buttons are what a
                  keyboard and a screen reader use. */}
              <button
                type="button"
                tabIndex={-1}
                aria-hidden="true"
                className="studio-library-row__hit"
                disabled={busy}
                onClick={() => void choose(template)}
              />
              <div className="studio-library-thumb" aria-hidden="true" inert>
                <div className="studio-library-thumb__canvas">
                  {renderPreview(template)}
                </div>
              </div>
              <div className="studio-library-row__text">
                <Name>{template.labels[locale].name}</Name>
                <p>{template.labels[locale].description}</p>
              </div>
              <div className="studio-library-row__actions">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("previewNamed", {
                    name: template.labels[locale].name,
                  })}
                  title={t("previewAction")}
                  onClick={(event) => preview(template, event.currentTarget)}
                >
                  <EyeIcon aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="icon-sm"
                  aria-label={t("addNamed", {
                    name: template.labels[locale].name,
                  })}
                  title={t("add")}
                  disabled={busy}
                  onClick={() => void choose(template)}
                >
                  <PlusIcon aria-hidden="true" />
                </Button>
              </div>
            </article>
          ) : (
            <article
              key={template.id}
              className="group flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background shadow-xs transition-colors hover:border-primary/50"
            >
              <div className="relative aspect-video overflow-hidden bg-muted">
                <div
                  className="pointer-events-none absolute inset-0 overflow-hidden"
                  aria-hidden="true"
                  inert
                >
                  <div className="w-[300%] origin-top-left scale-[0.3333333333]">
                    {renderPreview(template)}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  className="absolute inset-0 h-full w-full rounded-none border-0 p-0 hover:bg-transparent"
                  aria-label={t("previewNamed", {
                    name: template.labels[locale].name,
                  })}
                  onClick={(event) => preview(template, event.currentTarget)}
                >
                  <span className="pointer-events-none absolute right-2 bottom-2 flex items-center gap-1 rounded-md border bg-background/95 px-2 py-1 text-xs font-medium shadow-sm">
                    <EyeIcon className="size-3.5" aria-hidden="true" />
                    {t("previewAction")}
                  </span>
                </Button>
              </div>
              <div className="flex flex-1 flex-col gap-2 p-3">
                <Name className="text-sm leading-snug font-semibold">
                  {template.labels[locale].name}
                </Name>
                <p className="line-clamp-2 flex-1 text-xs leading-relaxed text-muted-foreground">
                  {template.labels[locale].description}
                </p>
                {template.contentProfiles?.length ? (
                  <p className="text-xs text-muted-foreground">
                    {t("contentLength", {
                      range: [
                        ...new Set([
                          template.contentProfiles[0],
                          template.contentProfiles.at(-1),
                        ]),
                      ].join("–"),
                    })}
                  </p>
                ) : null}
                <div className="flex items-center justify-between gap-2 pt-1">
                  <span className="min-w-0 text-xs text-muted-foreground">
                    {template.kind === "default"
                      ? t("universal")
                      : template.industries
                          .map(
                            (industryId) =>
                              sectionIndustries().find(
                                (item) => item.id === industryId,
                              )?.labels[locale],
                          )
                          .join(", ")}
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    aria-label={t("addNamed", {
                      name: template.labels[locale].name,
                    })}
                    disabled={busy}
                    onClick={() => void choose(template)}
                  >
                    <PlusIcon aria-hidden="true" />
                    {t("add")}
                  </Button>
                </div>
              </div>
            </article>
          ),
        )}
      </div>
      {ordered.length > limit && (
        <Button
          type="button"
          variant="outline"
          className={`h-auto w-full whitespace-normal py-2 ${compact ? "min-h-9 text-xs" : "min-h-10"}`}
          onClick={() => setLimit((value) => value + 12)}
        >
          {t("showMore", { remaining: ordered.length - limit })}
        </Button>
      )}
      {templates.length === 0 && (
        <p
          role="status"
          className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
        >
          {t("empty")}
        </p>
      )}
      {compact && details}
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setSelected(null);
        }}
      >
        <DialogContent
          className="flex max-h-[90dvh] flex-col overflow-hidden sm:max-w-5xl"
          closeLabel={common("close")}
          finalFocus={previewTrigger}
        >
          {selected && (
            <>
              <DialogHeader className="pr-8">
                <DialogTitle>{selected.labels[locale].name}</DialogTitle>
                <DialogDescription>
                  {selected.labels[locale].usage}
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div
                  className="flex gap-1 rounded-lg bg-muted p-1"
                  role="group"
                  aria-label={t("preview")}
                >
                  <Button
                    type="button"
                    size="sm"
                    variant={mobile ? "ghost" : "secondary"}
                    aria-pressed={!mobile}
                    onClick={() => setMobile(false)}
                  >
                    <MonitorIcon aria-hidden="true" />
                    {t("desktop")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={mobile ? "secondary" : "ghost"}
                    aria-pressed={mobile}
                    onClick={() => setMobile(true)}
                  >
                    <SmartphoneIcon aria-hidden="true" />
                    {t("mobile")}
                  </Button>
                </div>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => void choose(selected)}
                >
                  <PlusIcon aria-hidden="true" />
                  {t("addNamed", { name: selected.labels[locale].name })}
                </Button>
              </div>
              {feedback}
              <section
                aria-label={t("preview")}
                className="min-h-0 overflow-auto rounded-lg border bg-muted p-3"
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("a"))
                    event.preventDefault();
                }}
              >
                <div
                  className="mx-auto max-w-full overflow-hidden rounded-md bg-background shadow-sm"
                  style={{ width: mobile ? 390 : "100%" }}
                >
                  {renderPreview(selected)}
                </div>
              </section>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
