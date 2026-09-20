"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { PageSummary } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { PageEditor } from "./page-editor";

export function PageStudio({
  page,
  onChanged,
}: {
  page: PageSummary;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites.studio");
  const [open, setOpen] = useState(true);
  const [confirmExit, setConfirmExit] = useState(false);
  const [exitState, setExitState] = useState({ dirty: false, busy: true });
  function changeOpen(next: boolean) {
    if (!next && exitState.busy) return;
    if (!next && exitState.dirty) {
      setConfirmExit(true);
      return;
    }
    setOpen(next);
  }
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger render={<Button type="button" />}>
        {t("openStudio")}
      </DialogTrigger>
      <DialogContent
        fullScreen
        showCloseButton={false}
        className="flex flex-col gap-0"
      >
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <DialogTitle className="truncate">
              {t("studioTitle", { page: page.name })}
            </DialogTitle>
            <DialogDescription>{t("studioDescription")}</DialogDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={exitState.busy}
            onClick={() => changeOpen(false)}
          >
            {t("backToPages")}
          </Button>
        </header>
        <div
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-6"
          data-testid="fullscreen-studio"
        >
          {open && (
            <PageEditor
              page={page}
              onChanged={onChanged}
              onExitStateChange={setExitState}
            />
          )}
        </div>
        <Dialog open={confirmExit} onOpenChange={setConfirmExit}>
          <DialogContent>
            <DialogTitle>{t("unsavedTitle")}</DialogTitle>
            <DialogDescription>{t("unsavedDescription")}</DialogDescription>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                autoFocus
                type="button"
                variant="outline"
                onClick={() => setConfirmExit(false)}
              >
                {t("keepEditing")}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => {
                  setConfirmExit(false);
                  setOpen(false);
                  setExitState({ dirty: false, busy: true });
                }}
              >
                {t("discardChanges")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
