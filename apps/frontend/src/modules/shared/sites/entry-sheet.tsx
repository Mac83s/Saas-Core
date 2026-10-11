"use client";

/** One entry opened for work (PR1g): everything the panel offers for it — its
 *  words, address, categories, tags, schedule, translations and blocks — in a
 *  side sheet over the list, not below it. The editor's own behaviour is
 *  untouched; this only decides where it stands and what closing it costs:
 *  Escape, the close button, the backdrop and a swipe all ask first when the
 *  editor holds changes that are not saved. */

import { useCallback, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { EyeOffIcon, SendIcon, Trash2Icon } from "lucide-react";

import type { ContentCollection, ContentEntry } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@saas-core/ui/components/sheet";

import { EntryAddress } from "./entry-address";
import { EntryCategories } from "./entry-categories";
import { EntryEditor } from "./entry-editor";
import { EntryMetadata } from "./entry-metadata";
import { EntrySchedule } from "./entry-schedule";
import { EntryTags } from "./entry-tags";
import { EntryTranslations } from "./entry-translations";

export function EntrySheet({
  entry,
  collection,
  siteId,
  busy,
  languageName,
  stateLabel,
  returnFocus,
  onClose,
  onChanged,
  onPublish,
  onWithdraw,
  onRemove,
  removeDialog,
}: {
  entry: ContentEntry;
  collection: ContentCollection | null;
  siteId: string;
  /** A panel action is running: the footer's buttons wait. */
  busy: boolean;
  languageName: string;
  stateLabel: string;
  /** The row's own button, to land on again when the sheet is closed. */
  returnFocus: () => HTMLElement | null;
  onClose: () => void;
  /** The list is asked for again: the entry changed. */
  onChanged: () => Promise<void>;
  onPublish: (entry: ContentEntry) => void;
  onWithdraw: (entry: ContentEntry) => void;
  onRemove: (entry: ContentEntry) => void;
  /** The removal dialog while it is open, drawn inside the sheet: the page
   *  behind a modal sheet cannot take a second modal. */
  removeDialog?: ReactNode;
}) {
  const t = useTranslations("Sites");
  const sheet = useTranslations("Sites.entrySheet");
  const common = useTranslations("Common");
  const [exit, setExit] = useState({ dirty: false, busy: false });
  const [metadataDirty, setMetadataDirty] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const dirty = exit.dirty || metadataDirty;
  // The editor reports on every change of its state; a stable callback keeps
  // that from being a render per keystroke here.
  const onExitState = useCallback(
    (state: { dirty: boolean; busy: boolean }) => setExit(state),
    [],
  );
  const reload = useCallback(async () => {
    await onChanged();
  }, [onChanged]);
  function requestClose() {
    // An answer is being written to the server: leaving now would drop it.
    if (exit.busy) return;
    if (dirty) {
      setConfirming(true);
      return;
    }
    onClose();
  }

  const published = entry.state === "published";
  const blocked = busy || dirty;

  return (
    <Sheet
      onOpenChange={(next) => {
        if (!next) requestClose();
      }}
      open
    >
      <SheetContent
        className="h-dvh max-h-none w-[min(55rem,100vw)] rounded-none"
        closeLabel={common("close")}
        finalFocus={() => returnFocus()}
      >
        <SheetHeader>
          <SheetTitle className="wrap-anywhere">{entry.title}</SheetTitle>
          <SheetDescription className="flex flex-wrap items-center gap-2">
            <span>{languageName}</span>
            <Badge variant={published ? "default" : "secondary"}>
              {stateLabel}
            </Badge>
            {dirty ? (
              <Badge variant="neutral">{sheet("unsavedBadge")}</Badge>
            ) : null}
          </SheetDescription>
        </SheetHeader>

        <SheetBody className="space-y-6 py-4">
          <EntryMetadata
            entry={entry}
            key={`metadata-${entry.id}`}
            onChanged={reload}
            onDirtyChange={setMetadataDirty}
          />
          <EntryAddress
            collection={collection}
            entry={entry}
            key={`address-${entry.id}`}
            onChanged={reload}
          />
          <EntryCategories
            entry={entry}
            key={`categories-${entry.id}-${entry.categories.map((category) => category.id).join(",")}`}
            onChanged={reload}
            siteId={siteId}
          />
          <EntryTags
            entry={entry}
            key={`tags-${entry.id}-${entry.tags.map((tag) => tag.slug).join(",")}`}
            onChanged={reload}
          />
          <EntrySchedule
            entry={entry}
            key={`schedule-${entry.id}-${entry.schedule_state}`}
            onChanged={reload}
          />
          <EntryTranslations
            entry={entry}
            key={`translations-${entry.id}`}
            onCreated={() => void reload()}
          />
          <EntryEditor
            entry={entry}
            key={entry.id}
            locked={collection?.automation_policy === "automated"}
            onExitStateChange={onExitState}
            onSaved={() => void reload()}
            proposal={entry.draft_author === "automation"}
          />
        </SheetBody>

        {/* What the list's row offers beside „Edytuj”, kept at hand: the
            sheet covers the list, and closing it first to publish would be
            a step nobody asked for. */}
        <SheetFooter>
          <Button
            disabled={busy}
            onClick={() => onRemove(entry)}
            type="button"
            variant="outline"
          >
            <Trash2Icon aria-hidden="true" />
            {t("entryRemoval.action")}
          </Button>
          {published ? (
            <Button
              disabled={busy}
              onClick={() => onWithdraw(entry)}
              type="button"
              variant="outline"
            >
              <EyeOffIcon aria-hidden="true" />
              {sheet("withdraw")}
            </Button>
          ) : null}
          <Button
            disabled={blocked}
            onClick={() => onPublish(entry)}
            title={dirty ? sheet("saveFirst") : undefined}
            type="button"
          >
            <SendIcon aria-hidden="true" />
            {sheet(published ? "republish" : "publish")}
          </Button>
        </SheetFooter>

        <Dialog onOpenChange={setConfirming} open={confirming}>
          <DialogContent>
            <DialogTitle>{sheet("unsavedTitle")}</DialogTitle>
            <DialogDescription>{sheet("unsavedDescription")}</DialogDescription>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                autoFocus
                onClick={() => setConfirming(false)}
                type="button"
                variant="outline"
              >
                {sheet("keepEditing")}
              </Button>
              <Button
                onClick={() => {
                  setConfirming(false);
                  onClose();
                }}
                type="button"
                variant="destructive"
              >
                {sheet("discard")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
        {removeDialog}
      </SheetContent>
    </Sheet>
  );
}
