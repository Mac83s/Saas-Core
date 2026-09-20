"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  availableSectionTemplates,
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
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { materializeTemplatePhoto } from "@saas-core/api-client";
import { sectionPreview } from "./template-media-preview";
import { registry, editableBlocks, type BlockFormValues } from "./block-form";

const tokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

export function SectionLibrary({
  onAdd,
  triggerLabel,
  onBusyChange,
}: {
  onAdd: (block: BlockFormValues) => void;
  triggerLabel?: string;
  onBusyChange?: (busy: boolean) => void;
}) {
  const t = useTranslations("Sites.sectionLibrary");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) setOpen(next);
      }}
    >
      <DialogTrigger render={<Button type="button" variant="outline" />}>
        {triggerLabel ?? t("open")}
      </DialogTrigger>
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
  const id = useId();
  const locale = useLocale() === "en" ? "en" : "pl";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
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
  const [industry, setIndustry] = useState("");
  const [blockType, setBlockType] = useState("");
  const [selected, setSelected] = useState<SectionTemplate | null>(null);
  const [mobile, setMobile] = useState(false);
  const previewRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (selected) previewRef.current?.focus();
  }, [selected]);
  const templates = useMemo(
    () =>
      availableSectionTemplates(registry, {
        entitlements: ["sites.enabled"],
        modules: ["shared.sites"],
        industry,
        blockType,
      }),
    [industry, blockType],
  );
  const ordered = useMemo(() => {
    const groups = ["core.hero", "core.feature_list", "core.faq"].map((type) =>
      templates.filter((item) => item.blockType === type),
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
    const seeded = sectionTemplateBlock(template, locale, registry);
    if (!template.sampleMedia) {
      onAdd(editableBlocks([seeded])[0]);
      return;
    }
    pending.current = true;
    setBusy(true);
    setError(false);
    onBusyChange?.(true);
    try {
      const photo = template.sampleMedia;
      if (!receipts.current.has(photo.id))
        receipts.current.set(
          photo.id,
          `template-photo-${globalThis.crypto.randomUUID()}`,
        );
      const result = await materializeTemplatePhoto(
        photo.id,
        receipts.current.get(photo.id)!,
      );
      if (!mounted.current) return;
      seeded.data.image = { asset_id: result.asset_id, alt: photo.alt[locale] };
      registry.validate(seeded);
      onAdd(editableBlocks([seeded])[0]);
    } catch {
      if (mounted.current) setError(true);
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
  return (
    <div className="space-y-4">
      <div className={compact ? "grid gap-3" : "grid gap-4 sm:grid-cols-2"}>
        <Field>
          <FieldLabel htmlFor={`${id}-industry`}>{t("industry")}</FieldLabel>
          <NativeSelect
            id={`${id}-industry`}
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
        <Field>
          <FieldLabel htmlFor={`${id}-category`}>{t("category")}</FieldLabel>
          <NativeSelect
            id={`${id}-category`}
            value={blockType}
            onChange={(event) => {
              setBlockType(event.target.value);
              setLimit(12);
              setSelected(null);
            }}
          >
            <option value="">{t("allCategories")}</option>
            {["hero", "feature_list", "faq"].map((name) => (
              <option key={name} value={`core.${name}`}>
                {t(name)}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <p className="text-sm text-muted-foreground">{t("universalIncluded")}</p>
      <p className="text-xs text-muted-foreground">{t("samplePhotos")}</p>
      {busy && <p role="status">{t("preparingPhoto")}</p>}
      {error && <p role="alert">{t("photoError")}</p>}
      <div
        className={
          compact ? "grid gap-3" : "grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
        }
      >
        {ordered.slice(0, limit).map((template) => (
          <article
            key={template.id}
            className="flex min-w-0 flex-col gap-3 rounded-xl border p-4"
          >
            <div
              className="h-28 overflow-hidden rounded-md border bg-background"
              aria-hidden="true"
              inert
            >
              <div className="pointer-events-none w-[720px] origin-top-left scale-[0.35]">
                {renderPreview(template)}
              </div>
            </div>
            <h3 className="break-words font-semibold">
              {template.labels[locale].name}
            </h3>
            <p className="text-xs text-muted-foreground">
              {template.kind === "default"
                ? t("universal")
                : template.industries
                    .map(
                      (id) =>
                        sectionIndustries().find((item) => item.id === id)
                          ?.labels[locale],
                    )
                    .join(", ")}
            </p>
            <p className="flex-1 text-sm">
              {template.labels[locale].description}
            </p>
            <div
              className={
                compact ? "flex flex-col gap-2" : "flex flex-wrap gap-2"
              }
            >
              <Button
                type="button"
                variant="outline"
                aria-label={t("previewNamed", {
                  name: template.labels[locale].name,
                })}
                onClick={() => setSelected(template)}
              >
                {t("preview")}
              </Button>
              <Button
                type="button"
                aria-label={t("addNamed", {
                  name: template.labels[locale].name,
                })}
                disabled={busy}
                onClick={() => void choose(template)}
              >
                {t("add")}
              </Button>
            </div>
          </article>
        ))}
      </div>
      {ordered.length > limit && (
        <Button
          type="button"
          variant="outline"
          onClick={() => setLimit((value) => value + 12)}
        >
          {t("showMore", { remaining: ordered.length - limit })}
        </Button>
      )}
      {templates.length === 0 && <p role="status">{t("empty")}</p>}
      {selected && (
        <section
          className="space-y-3 rounded-xl border p-4"
          aria-label={t("preview")}
          ref={previewRef}
          tabIndex={-1}
        >
          <h3 className="break-words font-semibold">
            {selected.labels[locale].name}
          </h3>
          <p>{selected.labels[locale].usage}</p>
          <p className="text-sm text-muted-foreground">{t("mobileBehavior")}</p>
          <Button
            type="button"
            variant="outline"
            aria-pressed={mobile}
            onClick={() => setMobile(!mobile)}
          >
            {t("mobile")}
          </Button>
          <div
            className="mx-auto max-w-full overflow-hidden border bg-background"
            style={{ width: mobile ? 390 : "100%" }}
          >
            {renderPreview(selected)}
          </div>
          <Button
            type="button"
            disabled={busy}
            onClick={() => void choose(selected)}
          >
            {t("addNamed", { name: selected.labels[locale].name })}
          </Button>
        </section>
      )}
    </div>
  );
}
