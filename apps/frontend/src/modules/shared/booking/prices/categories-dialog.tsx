"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { PencilIcon } from "lucide-react";

import {
  createParticipantCategory,
  updateParticipantCategory,
  type ParticipantCategory,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { useDataTableLabels } from "#lib/data-table-labels";
import { refusal } from "./price-dialog";

/**
 * „Kategorie uczestników” (ADR-072 §6): who comes when it changes the price —
 * a child, a senior, a dog. A category is never deleted, only switched off:
 * bookings name it.
 */
export function CategoriesDialog({
  categories,
  finalFocus,
  onChanged,
  onOpenChange,
}: {
  categories: ParticipantCategory[];
  finalFocus: HTMLElement | null;
  /** After each write: the lists that name categories read them again. */
  onChanged: () => Promise<void> | void;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("PriceList");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const [editing, setEditing] = useState<ParticipantCategory>();
  const [name, setName] = useState("");
  const [counts, setCounts] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  // One key per thing asked: a double click saves once, the next save is new.
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    crypto.randomUUID(),
  );

  const start = (item?: ParticipantCategory) => {
    setEditing(item);
    setName(item?.name ?? "");
    setCounts(item?.counts_towards_capacity ?? true);
    setProblem(undefined);
  };

  async function write(
    action: () => Promise<ParticipantCategory>,
    said: string,
  ) {
    setBusy(true);
    setProblem(undefined);
    try {
      const saved = await action();
      setNotice(t(said as "categorySaved", { name: saved.name }));
      start();
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    } finally {
      setIdempotencyKey(crypto.randomUUID());
      setBusy(false);
      await onChanged();
    }
  }

  const save = () => {
    if (!name.trim()) return setProblem(t("categoryNameRequired"));
    const data = { name: name.trim(), counts_towards_capacity: counts };
    return void write(
      () =>
        editing
          ? updateParticipantCategory(
              editing.id,
              { ...data, expected_version: editing.version },
              idempotencyKey,
            )
          : createParticipantCategory(data, idempotencyKey),
      editing ? "categorySaved" : "categoryAdded",
    );
  };

  const columns: ColumnDef<ParticipantCategory, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colCategory"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <p className="font-medium wrap-anywhere">
          {item.name}
          {item.active ? null : (
            <Badge className="ml-2" variant="outline">
              {t("off")}
            </Badge>
          )}
        </p>
      ),
    },
    {
      id: "capacity",
      header: t("colCapacity"),
      enableSorting: false,
      cell: ({ row: { original: item } }) =>
        t(item.counts_towards_capacity ? "countsYes" : "countsNo"),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
        <RowActions
          items={[
            {
              label: t("editFor", { name: item.name }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              onSelect: () => start(item),
            },
            {
              label: t(item.active ? "switchOff" : "switchOn"),
              onSelect: () =>
                void write(
                  () =>
                    updateParticipantCategory(
                      item.id,
                      { active: !item.active, expected_version: item.version },
                      crypto.randomUUID(),
                    ),
                  item.active ? "categoryOff" : "categoryOn",
                ),
            },
          ]}
          label={t("actionsFor", { name: item.name })}
        />
      ),
    },
  ];

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("categoriesTitle")}</DialogTitle>
          <DialogDescription>{t("categoriesDescription")}</DialogDescription>
        </DialogHeader>
        <p
          className="text-sm text-success-foreground empty:hidden"
          role="status"
        >
          {notice}
        </p>
        <DataTable
          caption={t("categoriesTitle")}
          columns={columns}
          data={categories}
          getRowId={(item) => item.id}
          labels={{ ...labels, empty: t("noCategories") }}
        />
        <form
          className="space-y-3 rounded-lg border p-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <p className="text-sm font-medium">
            {editing
              ? t("categoryEditTitle", { name: editing.name })
              : t("categoryNewTitle")}
          </p>
          <Field>
            <FieldLabel htmlFor="category-name">{t("categoryName")}</FieldLabel>
            <Input
              autoComplete="off"
              id="category-name"
              maxLength={160}
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
          </Field>
          <label
            className="flex min-h-11 items-center gap-2 text-sm"
            htmlFor="category-counts"
          >
            <input
              checked={counts}
              className="size-4 shrink-0"
              id="category-counts"
              onChange={(event) => setCounts(event.target.checked)}
              type="checkbox"
            />
            {t("categoryCounts")}
          </label>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} type="submit">
              {t(editing ? "categorySave" : "categoryAdd")}
            </Button>
            {editing ? (
              <Button onClick={() => start()} type="button" variant="outline">
                {common("cancel")}
              </Button>
            ) : null}
          </div>
        </form>
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {common("close")}
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
