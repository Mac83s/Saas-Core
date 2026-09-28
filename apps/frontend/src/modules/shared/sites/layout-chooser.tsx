"use client";

import { useContext, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  hiddenFields,
  type BlockImageRenderer,
  type JsonObject,
  type SectionTemplate,
} from "@saas-core/site-blocks";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { LayoutGridIcon } from "lucide-react";

import { blockPayload, registry } from "./block-form";
import { PageEditorContext } from "./page-editor-context";

/** A photo's place in a miniature: the frame without fetching the picture —
 *  one section, dozens of layouts. */
const photoPlaceholder: BlockImageRenderer = (image) => (
  <span className="studio-layout-photo" role="img" aria-label={image.alt} />
);

/** Every layout of the section drawn with the section's own content, before
 *  anything changes: what each one shows and what it leaves out. Choosing one
 *  is the same one undo step as the select beside it (F3-Z2). */
export function LayoutChooser({
  type,
  data,
  layouts,
  current,
  locale,
  onChoose,
}: {
  type: string;
  data: JsonObject;
  layouts: readonly SectionTemplate[];
  current: string;
  locale: "pl" | "en";
  onChoose: (layout: string) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const look = useContext(PageEditorContext)?.look ?? "site-theme";
  const [open, setOpen] = useState(false);
  const block = (layout: string) =>
    blockPayload({ block_type: type, data: { ...data, layout } });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button type="button" variant="outline" size="sm" />}
      >
        <LayoutGridIcon aria-hidden="true" />
        {t("sectionLibrary.compareLayouts")}
      </DialogTrigger>
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-6xl"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{t("sectionLibrary.compareLayouts")}</DialogTitle>
          <DialogDescription>
            {t("sectionLibrary.compareLayoutsHint")}
          </DialogDescription>
        </DialogHeader>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {layouts.map((template) => {
            const candidate = block(template.layout);
            let preview: ReactNode;
            let hidden: string[] = [];
            try {
              preview = registry.render(
                candidate,
                template.id,
                undefined,
                photoPlaceholder,
              );
              hidden = hiddenFields(candidate, registry).map(
                ({ field, parent }) =>
                  parent
                    ? `${t(parent.labelKey)}: ${t(field.labelKey)}`
                    : t(field.labelKey),
              );
            } catch {
              preview = null;
            }
            const name = template.labels[locale].name;
            const chosen = template.layout === current;
            return (
              <li
                key={template.id}
                className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background"
              >
                <div className="relative aspect-video overflow-hidden bg-muted">
                  <div
                    className="pointer-events-none absolute inset-0 overflow-hidden"
                    aria-hidden="true"
                    inert
                  >
                    <div
                      className={`${look} w-[300%] origin-top-left scale-[0.3333333333]`}
                    >
                      {preview ?? (
                        <p className="p-6 text-sm">{t("studio.incomplete")}</p>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3">
                  <h3 className="text-sm font-semibold">{name}</h3>
                  <p className="flex-1 text-xs text-muted-foreground">
                    {hidden.length
                      ? t("sectionLibrary.layoutHides", {
                          fields: hidden.join(", "),
                        })
                      : t("sectionLibrary.layoutShowsAll")}
                  </p>
                  {chosen ? (
                    <Badge variant="secondary" className="self-start">
                      {t("sectionLibrary.currentLayout")}
                    </Badge>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      className="self-start"
                      aria-label={t("sectionLibrary.useLayoutNamed", {
                        name,
                      })}
                      onClick={() => {
                        onChoose(template.layout);
                        setOpen(false);
                      }}
                    >
                      {t("sectionLibrary.useLayout")}
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
