"use client";

import { useContext, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ShuffleIcon } from "lucide-react";

import {
  convertSection,
  sectionConversions,
  type BlockImageRenderer,
  type ConversionBlocker,
  type SiteBlock,
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

import { blockOption, registry } from "./block-form";
import { PageEditorContext } from "./page-editor-context";

const photoPlaceholder: BlockImageRenderer = (image) => (
  <span className="studio-layout-photo" role="img" aria-label={image.alt} />
);

/**
 * „Zmień rodzaj sekcji” (F4-C): the section as each type the contract lets it
 * become, drawn with its own content, with what will not come along, what
 * waits to be filled in and what stops the change. Nothing changes until one
 * is chosen, and the change is one undo step like any other edit.
 */
export function SectionTypeChooser({
  block,
  locale,
  onConvert,
}: {
  /** The section as a save would send it. */
  block: SiteBlock;
  locale: "pl" | "en";
  onConvert: (block: SiteBlock) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const look = useContext(PageEditorContext)?.look ?? "site-theme";
  const [open, setOpen] = useState(false);
  if (sectionConversions(block.block_type, registry).length === 0) return null;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button type="button" variant="outline" size="sm" />}
      >
        <ShuffleIcon aria-hidden="true" />
        {t("sectionConversion.open")}
      </DialogTrigger>
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-4xl"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{t("sectionConversion.title")}</DialogTitle>
          <DialogDescription>
            {t("sectionConversion.description")}
          </DialogDescription>
        </DialogHeader>
        <ConversionOptions
          block={block}
          locale={locale}
          look={look}
          onConvert={(converted) => {
            onConvert(converted);
            setOpen(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

/** Rendered only while the dialog is open: a section still being filled in
 *  is converted — and drawn — when somebody asks, not on every keystroke. */
function ConversionOptions({
  block,
  locale,
  look,
  onConvert,
}: {
  block: SiteBlock;
  locale: "pl" | "en";
  look: string;
  onConvert: (block: SiteBlock) => void;
}) {
  const t = useTranslations("Sites");
  const typeName = (type: string) =>
    t(blockOption(type)?.labelKey ?? "addBlock");
  const blockerText = (blocker: ConversionBlocker) => {
    switch (blocker.kind) {
      case "tooMany":
        return t("sectionConversion.tooMany", {
          count: blocker.count,
          max: blocker.max,
        });
      case "tooLong":
        return t("sectionConversion.tooLong", {
          item: blocker.item + 1,
          max: blocker.max,
        });
      default:
        return t("sectionConversion.invalid");
    }
  };
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {sectionConversions(block.block_type, registry).map((conversion) => {
        const result = convertSection(block, conversion, registry, locale);
        const name = typeName(conversion.to);
        let preview: ReactNode = null;
        if (result.block)
          try {
            preview = registry.render(
              result.block,
              conversion.id,
              undefined,
              photoPlaceholder,
            );
          } catch {
            preview = null;
          }
        const lost = result.lost.map(({ field, parent }) =>
          parent
            ? `${t(parent.labelKey)}: ${t(field.labelKey)}`
            : t(field.labelKey),
        );
        return (
          <li
            className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background"
            key={conversion.id}
          >
            <div className="relative aspect-video overflow-hidden bg-muted">
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 overflow-hidden"
                inert
              >
                <div
                  className={`${look} w-[300%] origin-top-left scale-[0.3333333333]`}
                >
                  {preview}
                </div>
              </div>
            </div>
            <div className="flex flex-1 flex-col gap-2 p-3 text-sm">
              <h3 className="font-semibold">{name}</h3>
              {result.blockers.map((blocker, index) => (
                <p className="text-destructive" key={index}>
                  {blockerText(blocker)}
                </p>
              ))}
              {result.block && (
                <p className="text-muted-foreground">
                  {lost.length
                    ? t("sectionConversion.lost", { fields: lost.join(", ") })
                    : t("sectionConversion.nothingLost")}
                </p>
              )}
              {result.filled > 0 && (
                <p className="text-muted-foreground">
                  {t("sectionConversion.filled", { count: result.filled })}
                </p>
              )}
              <Button
                aria-label={t("sectionConversion.useNamed", { name })}
                className="self-start"
                disabled={!result.block}
                onClick={() => {
                  if (result.block) onConvert(result.block);
                }}
                size="sm"
                type="button"
              >
                {t("sectionConversion.use")}
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
