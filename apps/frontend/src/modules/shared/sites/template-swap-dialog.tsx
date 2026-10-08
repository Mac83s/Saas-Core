"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { SiteTemplate } from "@saas-core/api-client";
import {
  composeTemplateSwap,
  hiddenFields,
  offeredSectionTemplates,
  pageTemplateBlocks,
  planTemplateSwap,
  type PageTemplate,
  type SiteBlock,
  type TemplateSwap,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { FieldLegend, FieldSet } from "@saas-core/ui/components/field";

import {
  blockOptions,
  blockPayload,
  registry,
  toSiteBlock,
  type BlockFormValues,
} from "./block-form";

type Locale = "pl" | "en";

/** The sections a template brings, as the import would seed them. */
export function templateSections(
  template: PageTemplate | SiteTemplate,
  locale: Locale,
): SiteBlock[] {
  return "labels" in template
    ? pageTemplateBlocks(template, registry, locale)
    : template.version.blocks.map((block) => toSiteBlock(block));
}

const layoutNames = new Map<string, Record<Locale, string>>();
for (const template of offeredSectionTemplates()) {
  const key = `${template.blockType}|${template.layout}`;
  if (!layoutNames.has(key))
    layoutNames.set(key, {
      pl: template.labels.pl.name,
      en: template.labels.en.name,
    });
}

/**
 * „Zmień szablon strony” (F4-C, answer 5a of 28.09): before anything is
 * saved, the page's sections are matched to the new template's — same type,
 * then the same role — and the dialog shows where each goes, which of the
 * template's sections come with sample content and which of the page's have
 * no place. What happens to those is the operator's explicit choice. The
 * same plan goes to the API, so the preview is what the import does.
 */
export function TemplateSwapDialog({
  blocks,
  disabled,
  locale,
  onCancel,
  onConfirm,
  template,
  unsaved,
}: {
  blocks: readonly BlockFormValues[];
  disabled?: boolean;
  locale: Locale;
  onCancel: () => void;
  /** `null`: the template alone, the page's sections left in the history. */
  onConfirm: (swap: TemplateSwap | null) => void;
  template: PageTemplate | SiteTemplate | null;
  unsaved: boolean;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const choiceName = useId();
  const [appendUnplaced, setAppendUnplaced] = useState(true);
  const current = useMemo(() => blocks.map(blockPayload), [blocks]);
  const incoming = useMemo(
    () => (template ? templateSections(template, locale) : []),
    [locale, template],
  );
  const plan = useMemo(
    () => planTemplateSwap(current, incoming),
    [current, incoming],
  );
  const swap = useMemo(
    () =>
      composeTemplateSwap(current, incoming, plan, registry, appendUnplaced),
    [appendUnplaced, current, incoming, plan],
  );
  if (!template) return null;

  const typeName = (block: SiteBlock) =>
    t(
      blockOptions.find((option) => option.type === block.block_type)
        ?.labelKey ?? "addBlock",
    );
  const ownName = (block: SiteBlock) => {
    const title = block.data.title;
    return typeof title === "string" && title.trim()
      ? t("templateSwap.ownSection", {
          type: typeName(block),
          title: title.trim(),
        })
      : typeName(block);
  };
  const placeName = (block: SiteBlock) =>
    layoutNames.get(`${block.block_type}|${String(block.data.layout)}`)?.[
      locale
    ] ?? typeName(block);
  const name =
    "labels" in template ? template.labels[locale].name : template.name;
  const fresh = plan.slots.flatMap((index, slot) =>
    index === null ? [slot] : [],
  );

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent
        className="max-h-[90dvh] max-w-2xl overflow-y-auto"
        closeLabel={common("close")}
      >
        <DialogTitle>{t("templateSwap.title", { name })}</DialogTitle>
        <DialogDescription>{t("templateSwap.description")}</DialogDescription>
        {swap.kept.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">
              {t("templateSwap.kept", { count: swap.kept.length })}
            </h3>
            <ul className="space-y-2 text-sm">
              {swap.kept.map(({ slot, block }) => {
                const hidden = hiddenFields(block, registry);
                return (
                  <li className="rounded-lg border p-3" key={slot}>
                    {t("templateSwap.keptItem", {
                      section: ownName(current[plan.slots[slot]!]!),
                      place: placeName(incoming[slot]!),
                    })}
                    {hidden.length > 0 && (
                      <p className="mt-1 text-muted-foreground">
                        {t("sectionLibrary.hiddenFields", {
                          fields: hidden
                            .map(({ field, parent }) =>
                              parent
                                ? `${t(parent.labelKey)}: ${t(field.labelKey)}`
                                : t(field.labelKey),
                            )
                            .join(", "),
                        })}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {fresh.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">
              {t("templateSwap.fresh", { count: fresh.length })}
            </h3>
            <p className="text-sm text-muted-foreground">
              {t("templateSwap.freshHint")}
            </p>
            <ul className="list-disc space-y-1 ps-5 text-sm">
              {fresh.map((slot) => (
                <li key={slot}>{placeName(incoming[slot]!)}</li>
              ))}
            </ul>
          </section>
        )}
        {plan.unplaced.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">
              {t("templateSwap.unplaced", { count: plan.unplaced.length })}
            </h3>
            <ul className="list-disc space-y-1 ps-5 text-sm">
              {plan.unplaced.map((index) => (
                <li key={index}>{ownName(current[index]!)}</li>
              ))}
            </ul>
            <FieldSet>
              <FieldLegend variant="label">
                {t("templateSwap.unplacedChoice")}
              </FieldLegend>
              <div className="grid gap-1">
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={appendUnplaced}
                    className="size-4"
                    name={choiceName}
                    onChange={() => setAppendUnplaced(true)}
                    type="radio"
                  />
                  {t("templateSwap.append")}
                </label>
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={!appendUnplaced}
                    className="size-4"
                    name={choiceName}
                    onChange={() => setAppendUnplaced(false)}
                    type="radio"
                  />
                  {t("templateSwap.skip")}
                </label>
              </div>
            </FieldSet>
          </section>
        )}
        {unsaved && (
          <p className="text-sm" role="status">
            {t("templateSwap.unsaved")}
          </p>
        )}
        <DialogFooter>
          <Button onClick={onCancel} type="button" variant="outline">
            {common("cancel")}
          </Button>
          <Button
            disabled={disabled}
            onClick={() => onConfirm(null)}
            type="button"
            variant="outline"
          >
            {t("templateSwap.templateOnly")}
          </Button>
          <Button
            disabled={disabled}
            onClick={() => onConfirm(swap)}
            type="button"
          >
            {t("templateSwap.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
