"use client";

/** „Usuń wpis…” (CT2): one language version of an entry leaves the panel and,
 *  where it was published, the site. Asked of the server first, so the dialog
 *  says only what applies to this entry — and that the panel cannot bring it
 *  back. */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2Icon } from "lucide-react";

import {
  previewEntryRemoval,
  removeContentEntry,
  type ContentEntry,
  type EntryRemoval,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { sitesErrorMessage } from "./problem";
import { useLanguageName } from "./term-list-panel";

export function RemoveEntryDialog({
  entry,
  onClose,
  onRemoved,
}: {
  entry: ContentEntry;
  onClose: () => void;
  onRemoved: (removed: ContentEntry) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const languageName = useLanguageName();
  const [preview, setPreview] = useState<EntryRemoval>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let current = true;
    previewEntryRemoval(entry.id)
      .then((result) => {
        if (current) setPreview(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
  }, [entry.id, t]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      await removeContentEntry(entry.id);
      onRemoved(entry);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
      open
    >
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>
            {t("entryRemoval.title", { title: preview?.title ?? entry.title })}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          {preview === undefined && !problem ? (
            <p className="text-muted-foreground">{t("entryRemoval.loading")}</p>
          ) : null}
          {preview ? (
            <>
              <p>
                {preview.published && preview.path
                  ? t("entryRemoval.published", { path: preview.path })
                  : t("entryRemoval.notPublished")}
              </p>
              {preview.scheduled ? <p>{t("entryRemoval.scheduled")}</p> : null}
              {preview.other_languages.length > 0 ? (
                <p>
                  {t("entryRemoval.otherLanguages", {
                    language: languageName(preview.locale),
                    list: preview.other_languages
                      .map((other) => languageName(other.locale))
                      .join(", "),
                  })}
                </p>
              ) : null}
              {preview.machine_translation ? (
                <p>{t("entryRemoval.machine")}</p>
              ) : null}
              <p className="font-medium">{t("entryRemoval.irreversible")}</p>
            </>
          ) : null}
          {problem ? (
            <p className="text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            disabled={busy}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            {common("cancel")}
          </Button>
          <Button
            disabled={busy || preview === undefined}
            onClick={() => void confirm()}
            variant="destructive"
          >
            <Trash2Icon aria-hidden="true" />
            {t("entryRemoval.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
