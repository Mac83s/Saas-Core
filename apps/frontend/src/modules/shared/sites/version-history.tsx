"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { EyeIcon, HistoryIcon, RotateCcwIcon } from "lucide-react";
import {
  listPageVersions,
  type PageVersionSummary,
} from "@saas-core/api-client";
import { corePageTemplates } from "@saas-core/site-blocks";
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

import { sitesErrorMessage } from "./problem";

/** The page's history (F4-A): every saved version, how it came to be, and
 *  "Przywróć" — a new version with that version's content. Nothing in the
 *  history is ever rewritten, so a restore can be undone the same way. */
export function VersionHistory({
  pageId,
  dirty,
  disabled,
  onPreview,
  onRestore,
}: {
  pageId: string;
  /** Unsaved edits: restoring replaces them, so the button says so. */
  dirty: boolean;
  disabled: boolean;
  onPreview: (version: PageVersionSummary) => void;
  onRestore: (version: PageVersionSummary) => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<PageVersionSummary[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [problem, setProblem] = useState<string>();
  const [confirm, setConfirm] = useState<PageVersionSummary>();
  const [busy, setBusy] = useState(false);
  const loaded = useRef(false);
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const load = useCallback(
    async (cursor?: string) => {
      setProblem(undefined);
      try {
        const page = await listPageVersions(pageId, cursor);
        setItems((current) =>
          cursor ? [...current, ...page.items] : page.items,
        );
        setNext(page.next_cursor);
      } catch (error) {
        setProblem(sitesErrorMessage(error, t));
      }
    },
    [pageId, t],
  );
  useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    void load();
  }, [open, load]);
  const originLabel = (version: PageVersionSummary) => {
    if (version.origin === "template") {
      const [id] = version.origin_ref.split("@");
      const name = corePageTemplates().find((item) => item.id === id)?.labels[
        locale === "en" ? "en" : "pl"
      ].name;
      return t("versions.origin.template", { name: name ?? id });
    }
    if (version.origin === "restore")
      return t("versions.origin.restore", { number: version.origin_ref });
    if (version.automation) return t("versions.origin.automation");
    return t(
      `versions.origin.${
        ["change_set", "proposal_rejected", "save"].includes(version.origin)
          ? version.origin
          : "unknown"
      }`,
    );
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setOpen(next);
        // The history is read again the next time it opens.
        if (!next) {
          loaded.current = false;
          setConfirm(undefined);
        }
      }}
    >
      <DialogTrigger
        render={<Button type="button" variant="ghost" disabled={disabled} />}
      >
        <HistoryIcon aria-hidden="true" />
        {t("versions.open")}
      </DialogTrigger>
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{t("versions.title")}</DialogTitle>
          <DialogDescription>{t("versions.description")}</DialogDescription>
        </DialogHeader>
        {problem && (
          <p role="alert" className="text-sm text-destructive">
            {problem}
          </p>
        )}
        {confirm ? (
          <div className="space-y-3 rounded-lg border p-4">
            <p className="font-medium">
              {t("versions.confirmTitle", { number: confirm.number })}
            </p>
            <p className="text-sm text-muted-foreground">
              {t("versions.confirmText", { number: confirm.number })}
            </p>
            {dirty && (
              <p className="text-sm font-medium text-destructive">
                {t("versions.confirmDirty")}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setConfirm(undefined)}
              >
                {common("cancel")}
              </Button>
              <Button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await onRestore(confirm);
                    setConfirm(undefined);
                    setOpen(false);
                    loaded.current = false;
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <RotateCcwIcon aria-hidden="true" />
                {t("versions.restoreNamed", { number: confirm.number })}
              </Button>
            </div>
          </div>
        ) : null}
        <ul className="space-y-3" aria-label={t("versions.title")}>
          {items.map((version) => (
            <li
              key={version.id}
              className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {t("versionValue", { version: version.number })}
                  </span>
                  {version.current && <Badge>{t("current")}</Badge>}
                </div>
                <p className="text-sm">{originLabel(version)}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {version.created_by.email} ·{" "}
                  {dateFormatter.format(new Date(version.created_at))} ·{" "}
                  {t("versions.sections", { count: version.block_count })}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label={t("versions.previewNamed", {
                    number: version.number,
                  })}
                  onClick={() => onPreview(version)}
                >
                  <EyeIcon aria-hidden="true" />
                  {t("versions.preview")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={version.current || busy}
                  aria-label={t("versions.restoreNamed", {
                    number: version.number,
                  })}
                  onClick={() => setConfirm(version)}
                >
                  <RotateCcwIcon aria-hidden="true" />
                  {t("versions.restore")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
        {next && (
          <Button
            type="button"
            variant="outline"
            onClick={() => void load(next)}
          >
            {t("versions.more")}
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}
