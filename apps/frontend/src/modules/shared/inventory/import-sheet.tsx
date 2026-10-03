"use client";

import { useState, type ChangeEvent } from "react";
import { useTranslations } from "next-intl";
import { DownloadIcon } from "lucide-react";

import {
  applyInventoryImport,
  getInventoryImportTemplate,
  previewInventoryImport,
  type InventoryImportResult,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@saas-core/ui/components/sheet";

import { useDataTableLabels } from "#lib/data-table-labels";
import {
  locationLabel,
  problemText,
  useFormat,
  type InventoryData,
} from "./shared";

type Row = InventoryImportResult["rows"][number];
type Chosen = { name: string; content: string; key: string };

/**
 * A spreadsheet saves Polish letters as UTF-8 or, from an older Excel, as
 * Windows-1250. The file is read here and sent as text; nothing is uploaded
 * as a file and the server keeps none of it.
 */
export async function readCsv(file: File): Promise<string> {
  const bytes = await new Promise<ArrayBuffer>((done, failed) => {
    const reader = new FileReader();
    reader.onload = () => done(reader.result as ArrayBuffer);
    reader.onerror = () => failed(reader.error);
    reader.readAsArrayBuffer(file);
  });
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder("windows-1250").decode(bytes);
  }
}

/**
 * Katalog › Importuj z CSV (phase 10c): choose a file, see row by row what it
 * would do, then save all of it or nothing. A row with a problem blocks the
 * save and says which cell; a cell that looks like a formula is shown as text.
 */
export function ImportSheet({
  data,
  open,
  onClose,
  onImported,
}: {
  data: InventoryData;
  open: boolean;
  onClose: () => void;
  onImported: (notice: string) => void;
}) {
  const t = useTranslations("Inventory");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const { amount } = useFormat();
  const warehouses = data.locations.filter(
    (location) => location.kind === "warehouse" && location.active !== false,
  );
  const [locationId, setLocationId] = useState("");
  const [chosen, setChosen] = useState<Chosen>();
  const [preview, setPreview] = useState<InventoryImportResult>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const input = (content: string, place: string) => ({
    content,
    location_id: place || null,
  });

  async function look(next: Chosen, place: string) {
    setBusy(true);
    setProblem("");
    setPreview(undefined);
    try {
      setPreview(await previewInventoryImport(input(next.content, place)));
    } catch (error) {
      setProblem(problemText(error, t("importUnreadable")));
    } finally {
      setBusy(false);
    }
  }

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    // One key per file chosen: a retry after a lost answer saves once.
    const next = {
      name: file.name,
      content: await readCsv(file),
      key: crypto.randomUUID(),
    };
    setChosen(next);
    await look(next, locationId);
  }

  async function save() {
    if (!chosen) return;
    setBusy(true);
    setProblem("");
    try {
      const result = await applyInventoryImport(
        input(chosen.content, locationId),
        chosen.key,
      );
      onImported(
        t("importDone", {
          created: result.summary.created,
          updated: result.summary.updated,
        }),
      );
      close();
    } catch (error) {
      setProblem(problemText(error, t("failed")));
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setChosen(undefined);
    setPreview(undefined);
    setProblem("");
    onClose();
  }

  async function download() {
    const sheet = await getInventoryImportTemplate();
    // A BOM, so a spreadsheet opens the Polish letters as they are.
    const url = URL.createObjectURL(
      new Blob(["﻿", sheet.csv], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = sheet.filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  // „Jednostka: nieznana jednostka…” — the column by its name, the problem by
  // its code in the reader's language; the server's sentence when a code is new.
  const said = (one: Row["problems"][number]) => {
    const column = t.has(`importColumn_${one.field}`)
      ? t(`importColumn_${one.field}`)
      : one.field;
    const words = t.has(`importProblem_${one.code}`)
      ? t(`importProblem_${one.code}`)
      : one.message;
    return `${column}: ${words}`;
  };

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "row",
      accessorKey: "line",
      header: t("importRow"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{row.name || "—"}</p>
          <p className="text-xs text-muted-foreground">
            {t("importLine", { line: row.line })}
            {row.sku ? ` · ${row.sku}` : ""}
          </p>
        </>
      ),
    },
    {
      id: "action",
      // Problems first when sorted: they are what stops the save.
      accessorFn: (row) => (row.action === "error" ? 0 : 1),
      header: t("importAction"),
      meta: { long: true },
      cell: ({ row: { original: row } }) => (
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-2">
            <Badge
              variant={
                row.action === "error"
                  ? "destructive"
                  : row.action === "unchanged"
                    ? "neutral"
                    : "info"
              }
            >
              {t(`importAction_${row.action}`)}
            </Badge>
            {row.quantity ? (
              <span className="text-sm">
                {t("importReceives", { quantity: amount(row.quantity) })}
              </span>
            ) : null}
          </p>
          {row.problems.map((one) => (
            <p
              className="text-sm text-destructive"
              key={`${one.field}:${one.code}`}
            >
              {said(one)}
            </p>
          ))}
          {row.warnings.map((one) => (
            <p
              className="text-sm text-muted-foreground"
              key={`${one.field}:${one.code}`}
            >
              {said(one)}
            </p>
          ))}
        </div>
      ),
    },
  ];

  const summary = preview?.summary;
  const rows = [...(preview?.rows ?? [])].sort(
    (a, b) =>
      Number(a.action !== "error") - Number(b.action !== "error") ||
      a.line - b.line,
  );

  return (
    <Sheet onOpenChange={(next) => (next ? null : close())} open={open}>
      <SheetContent
        className="md:w-[min(44rem,100vw)]"
        closeLabel={common("close")}
      >
        <SheetHeader>
          <SheetTitle>{t("importTitle")}</SheetTitle>
          <SheetDescription>{t("importDescription")}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          <Button onClick={() => void download()} variant="outline">
            <DownloadIcon aria-hidden="true" />
            {t("importTemplate")}
          </Button>
          <Field>
            <FieldLabel htmlFor="import-file">{t("importFile")}</FieldLabel>
            <Input
              accept=".csv,text/csv"
              id="import-file"
              onChange={(event) => void choose(event)}
              type="file"
            />
          </Field>
          {warehouses.length > 1 ? (
            <Field>
              <FieldLabel htmlFor="import-location">
                {t("importLocation")}
              </FieldLabel>
              <NativeSelect
                id="import-location"
                onChange={(event) => {
                  setLocationId(event.target.value);
                  if (chosen) void look(chosen, event.target.value);
                }}
                value={locationId}
              >
                <option value="">{t("importLocationMain")}</option>
                {warehouses
                  .filter((location) => !location.is_default)
                  .map((location) => (
                    <option key={location.id} value={location.id}>
                      {locationLabel(location)}
                    </option>
                  ))}
              </NativeSelect>
            </Field>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {summary ? (
            <div aria-live="polite" className="space-y-1 text-sm">
              <p className="font-medium">
                {t("importSummary", {
                  rows: summary.rows,
                  created: summary.created,
                  updated: summary.updated,
                  unchanged: summary.unchanged,
                })}
              </p>
              {summary.stock_lines ? (
                <p>{t("importStock", { count: summary.stock_lines })}</p>
              ) : null}
              {summary.new_categories.length ? (
                <p>
                  {t("importNewCategories", {
                    names: summary.new_categories.join(", "),
                  })}
                </p>
              ) : null}
              {preview.unknown_columns.length ? (
                <p className="text-muted-foreground">
                  {t("importUnknownColumns", {
                    names: preview.unknown_columns.join(", "),
                  })}
                </p>
              ) : null}
              {summary.invalid ? (
                <p className="text-destructive" role="alert">
                  {t("importInvalid", { count: summary.invalid })}
                </p>
              ) : null}
            </div>
          ) : null}
          {preview ? (
            <DataTable
              caption={t("importRows")}
              columns={columns}
              data={rows}
              getRowId={(row) => String(row.line)}
              labels={{ ...labels, empty: t("importNoRows") }}
              pageSize={25}
            />
          ) : null}
        </SheetBody>
        <SheetFooter>
          <Button
            disabled={busy || !summary || summary.invalid > 0 || !summary.rows}
            onClick={() => void save()}
          >
            {summary && !summary.invalid
              ? t("importSave", { count: summary.created + summary.updated })
              : t("importSaveIdle")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
