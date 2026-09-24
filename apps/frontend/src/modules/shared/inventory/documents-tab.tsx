"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CheckIcon, EyeIcon, PlusIcon, Trash2Icon } from "lucide-react";

import {
  correctStockDocument,
  createStockDocument,
  listStockDocuments,
  postStockDocument,
  type StockDocument,
  type StockDocumentKind,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelHelp, PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  FormDialog,
  locationLabel,
  problemText,
  useFormat,
  type InventoryData,
  type PageFrame,
} from "./shared";

const KINDS = ["PZ", "WZ", "RW", "PW", "MM", "INW"] as const;
/** Skąd towar schodzi i dokąd przybywa — to samo, co sprawdza API. */
const FROM: StockDocumentKind[] = ["WZ", "RW", "MM"];
const TO: StockDocumentKind[] = ["PZ", "PW", "MM", "INW"];
const PRICED: StockDocumentKind[] = ["PZ", "PW"];

type Line = { item_id: string; quantity: string; price: string };

/**
 * Dokumenty magazynowe. Szkic można poprawiać; zatwierdzenie nadaje numer i
 * zmienia stan. Zatwierdzonego nie zmienia się — pomyłkę prostuje korekta.
 */
export function DocumentsTab({
  data,
  reloads,
  onChanged,
  page,
}: {
  data: InventoryData;
  reloads: number;
  onChanged: (notice: string) => void;
  page: PageFrame;
}) {
  const t = useTranslations("Inventory");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const { amount, money } = useFormat();
  const [kindFilter, setKindFilter] = useState("");
  const [rows, setRows] = useState<StockDocument[] | undefined>();
  const [failed, setFailed] = useState(false);
  const [problem, setProblem] = useState("");
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<StockDocument | null>(null);
  const [correcting, setCorrecting] = useState<StockDocument | null>(null);
  const [correctionNote, setCorrectionNote] = useState("");
  const warehouse = data.locations.find((location) => location.is_default);
  const today = new Date().toISOString().slice(0, 10);
  const blank = () => ({
    id: crypto.randomUUID(),
    kind: "PZ" as StockDocumentKind,
    document_date: today,
    source: warehouse?.id ?? "",
    target: warehouse?.id ?? "",
    supplier: "",
    counterparty: "",
    note: "",
    post: true,
    lines: [{ item_id: "", quantity: "", price: "" }] as Line[],
  });
  const [draft, setDraft] = useState(blank);

  useEffect(() => {
    let current = true;
    listStockDocuments({ kind: kindFilter })
      .then((documents) => {
        if (!current) return;
        setRows(documents);
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [kindFilter, reloads]);

  const place = (id: string | null | undefined) => {
    const location = data.locations.find((one) => one.id === id);
    return location ? locationLabel(location) : "";
  };

  async function act(action: () => Promise<StockDocument>, done: string) {
    setProblem("");
    try {
      const document = await action();
      onChanged(t(done, { number: document.number }));
    } catch (error) {
      setProblem(problemText(error, t("failed")));
    }
  }

  async function save() {
    const kind = draft.kind;
    const document = await createStockDocument({
      id: draft.id,
      kind,
      document_date: draft.document_date,
      source_location_id: FROM.includes(kind) ? draft.source : null,
      target_location_id: TO.includes(kind) ? draft.target : null,
      supplier_id: kind === "PZ" && draft.supplier ? draft.supplier : null,
      counterparty: kind === "WZ" ? draft.counterparty : "",
      note: draft.note,
      lines: draft.lines
        .filter((line) => line.item_id && line.quantity !== "")
        .map((line) => ({
          item_id: line.item_id,
          quantity: line.quantity,
          unit_price_minor:
            PRICED.includes(kind) && line.price
              ? Math.round(Number(line.price) * 100)
              : null,
        })),
    });
    if (!draft.post) return onChanged(t("documentDrafted"));
    // A failed post keeps the dialog open; resubmitting reuses the draft's id,
    // so the API returns the same draft instead of making a second one.
    const posted = await postStockDocument(document.id);
    onChanged(t("documentPosted", { number: posted.number }));
  }

  const columns: ColumnDef<StockDocument, unknown>[] = [
    {
      id: "number",
      accessorFn: (row) => row.number || t("draft"),
      header: t("documentNumber"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium">
            {row.number || t("draft")}{" "}
            {row.corrects_id ? (
              <Badge variant="outline">{t("correction")}</Badge>
            ) : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {t(`kind_${row.kind}`)}
          </p>
        </>
      ),
    },
    { id: "date", accessorKey: "document_date", header: t("documentDate") },
    {
      id: "route",
      header: t("route"),
      enableSorting: false,
      accessorFn: (row) =>
        [place(row.source_location_id), place(row.target_location_id)]
          .filter(Boolean)
          .join(" → "),
    },
    {
      id: "status",
      accessorKey: "status",
      header: t("status"),
      cell: ({ row: { original: row } }) => (
        <Badge variant={row.status === "posted" ? "secondary" : "outline"}>
          {t(`status_${row.status}`)}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={[
            {
              label: t("view"),
              icon: <EyeIcon aria-hidden="true" />,
              inline: true,
              onSelect: () => setViewing(row),
            },
            ...(row.status === "draft"
              ? [
                  {
                    label: t("post"),
                    icon: <CheckIcon aria-hidden="true" />,
                    inline: true,
                    onSelect: () =>
                      void act(
                        () => postStockDocument(row.id),
                        "documentPosted",
                      ),
                  },
                ]
              : row.corrects_id
                ? []
                : [
                    {
                      label: t("correct"),
                      destructive: true,
                      separated: true,
                      onSelect: () => {
                        setCorrectionNote("");
                        setCorrecting(row);
                      },
                    },
                  ]),
          ]}
          label={t("actionsFor", { name: row.number || t("draft") })}
        />
      ),
    },
  ];

  const setLine = (index: number, patch: Partial<Line>) =>
    setDraft({
      ...draft,
      lines: draft.lines.map((line, at) =>
        at === index ? { ...line, ...patch } : line,
      ),
    });
  const locationOptions = data.locations
    .filter((location) => location.active)
    .map((location) => (
      <option key={location.id} value={location.id}>
        {locationLabel(location)}
      </option>
    ));

  return (
    <PanelPage
      {...page}
      actions={
        <Button
          onClick={() => {
            setDraft(blank());
            setCreating(true);
          }}
        >
          <PlusIcon aria-hidden="true" />
          {t("newDocument")}
        </Button>
      }
      aside={
        <PanelHelp title={t("kindsHelpTitle")}>
          <dl className="space-y-2">
            {KINDS.map((kind) => (
              <div key={kind}>
                <dt className="font-medium text-foreground">
                  {kind} · {t(`kind_${kind}`)}
                </dt>
                <dd>{t(`kindHelp_${kind}`)}</dd>
              </div>
            ))}
          </dl>
          <p>{t("correctionHelp")}</p>
        </PanelHelp>
      }
      asideLabel={t("helpLabel")}
      description={t("documentsDescription")}
    >
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("documentsCaption")}
          columns={columns}
          data={rows ?? []}
          getRowId={(row) => row.id}
          labels={{ ...labels, empty: t("documentsEmpty") }}
          loading={!rows}
          searchable
          searchText={(row) =>
            [
              row.number,
              t(`kind_${row.kind}`),
              row.counterparty,
              row.note,
            ].join(" ")
          }
          toolbar={
            <DataTableFilter
              id="documents-kind"
              label={t("kind")}
              onChange={(event) => setKindFilter(event.target.value)}
              value={kindFilter}
            >
              <option value="">{t("allKinds")}</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {t(`kind_${kind}`)}
                </option>
              ))}
            </DataTableFilter>
          }
        />
      )}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}

      <FormDialog
        description={t("newDocumentDescription")}
        onOpenChange={setCreating}
        onSubmit={save}
        open={creating}
        submitLabel={draft.post ? t("saveAndPost") : t("saveDraft")}
        title={t("newDocument")}
        wide
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="document-kind">{t("kind")}</FieldLabel>
            <NativeSelect
              id="document-kind"
              onChange={(event) =>
                setDraft({
                  ...draft,
                  kind: event.target.value as StockDocumentKind,
                })
              }
              value={draft.kind}
            >
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind} — {t(`kind_${kind}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor="document-date">{t("documentDate")}</FieldLabel>
            <Input
              id="document-date"
              onChange={(event) =>
                setDraft({ ...draft, document_date: event.target.value })
              }
              required
              type="date"
              value={draft.document_date}
            />
          </Field>
          {FROM.includes(draft.kind) ? (
            <Field>
              <FieldLabel htmlFor="document-source">{t("from")}</FieldLabel>
              <NativeSelect
                id="document-source"
                onChange={(event) =>
                  setDraft({ ...draft, source: event.target.value })
                }
                required
                value={draft.source}
              >
                {locationOptions}
              </NativeSelect>
            </Field>
          ) : null}
          {TO.includes(draft.kind) ? (
            <Field>
              <FieldLabel htmlFor="document-target">
                {draft.kind === "INW" ? t("counted") : t("to")}
              </FieldLabel>
              <NativeSelect
                id="document-target"
                onChange={(event) =>
                  setDraft({ ...draft, target: event.target.value })
                }
                required
                value={draft.target}
              >
                {locationOptions}
              </NativeSelect>
            </Field>
          ) : null}
          {draft.kind === "PZ" ? (
            <Field>
              <FieldLabel htmlFor="document-supplier">
                {t("supplier")}
              </FieldLabel>
              <NativeSelect
                id="document-supplier"
                onChange={(event) =>
                  setDraft({ ...draft, supplier: event.target.value })
                }
                value={draft.supplier}
              >
                <option value="">{t("noSupplier")}</option>
                {data.suppliers
                  .filter((supplier) => supplier.active !== false)
                  .map((supplier) => (
                    <option key={supplier.id} value={supplier.id}>
                      {supplier.name}
                    </option>
                  ))}
              </NativeSelect>
            </Field>
          ) : null}
          {draft.kind === "WZ" ? (
            <Field>
              <FieldLabel htmlFor="document-counterparty">
                {t("counterparty")}
              </FieldLabel>
              <Input
                id="document-counterparty"
                maxLength={160}
                onChange={(event) =>
                  setDraft({ ...draft, counterparty: event.target.value })
                }
                value={draft.counterparty}
              />
            </Field>
          ) : null}
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("lines")}</legend>
          {draft.kind === "INW" ? (
            <p className="text-sm text-muted-foreground">{t("countHint")}</p>
          ) : null}
          {draft.lines.map((line, index) => (
            <div className="flex flex-wrap items-end gap-2" key={index}>
              <Field className="min-w-48 flex-1">
                <FieldLabel htmlFor={`line-item-${index}`}>
                  {t("item")}
                </FieldLabel>
                <NativeSelect
                  id={`line-item-${index}`}
                  onChange={(event) =>
                    setLine(index, { item_id: event.target.value })
                  }
                  value={line.item_id}
                >
                  <option value="">{t("pickItem")}</option>
                  {data.items
                    .filter((item) => item.active)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </NativeSelect>
              </Field>
              <Field className="w-28">
                <FieldLabel htmlFor={`line-quantity-${index}`}>
                  {t("quantity")}
                </FieldLabel>
                <Input
                  id={`line-quantity-${index}`}
                  min="0"
                  onChange={(event) =>
                    setLine(index, { quantity: event.target.value })
                  }
                  step="0.001"
                  type="number"
                  value={line.quantity}
                />
              </Field>
              {PRICED.includes(draft.kind) ? (
                <Field className="w-32">
                  <FieldLabel htmlFor={`line-price-${index}`}>
                    {t("unitPrice")}
                  </FieldLabel>
                  <Input
                    id={`line-price-${index}`}
                    min="0"
                    onChange={(event) =>
                      setLine(index, { price: event.target.value })
                    }
                    step="0.01"
                    type="number"
                    value={line.price}
                  />
                </Field>
              ) : null}
              <Button
                aria-label={t("removeLine")}
                disabled={draft.lines.length === 1}
                onClick={() =>
                  setDraft({
                    ...draft,
                    lines: draft.lines.filter((_, at) => at !== index),
                  })
                }
                size="icon"
                type="button"
                variant="ghost"
              >
                <Trash2Icon aria-hidden="true" />
              </Button>
            </div>
          ))}
          <Button
            onClick={() =>
              setDraft({
                ...draft,
                lines: [
                  ...draft.lines,
                  { item_id: "", quantity: "", price: "" },
                ],
              })
            }
            type="button"
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("addLine")}
          </Button>
        </fieldset>

        <Field>
          <FieldLabel htmlFor="document-note">{t("notes")}</FieldLabel>
          <Input
            id="document-note"
            maxLength={240}
            onChange={(event) =>
              setDraft({ ...draft, note: event.target.value })
            }
            value={draft.note}
          />
        </Field>
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input
            checked={draft.post}
            className="size-4"
            onChange={(event) =>
              setDraft({ ...draft, post: event.target.checked })
            }
            type="checkbox"
          />
          {t("postNow")}
        </label>
      </FormDialog>

      <FormDialog
        description={t("correctDescription")}
        onOpenChange={(next) => setCorrecting(next ? correcting : null)}
        onSubmit={async () => {
          if (!correcting) return;
          const correction = await correctStockDocument(
            correcting.id,
            correctionNote,
          );
          onChanged(t("documentCorrected", { number: correction.number }));
        }}
        open={correcting !== null}
        submitLabel={t("correct")}
        title={t("correctTitle", { number: correcting?.number ?? "" })}
      >
        <Field>
          <FieldLabel htmlFor="correction-note">
            {t("correctReason")}
          </FieldLabel>
          <Input
            id="correction-note"
            maxLength={240}
            onChange={(event) => setCorrectionNote(event.target.value)}
            value={correctionNote}
          />
        </Field>
      </FormDialog>

      <Dialog
        onOpenChange={(next) => {
          if (!next) setViewing(null);
        }}
        open={viewing !== null}
      >
        <DialogContent className="sm:max-w-2xl" closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {viewing
                ? `${viewing.number || t("draft")} — ${t(`kind_${viewing.kind}`)}`
                : ""}
            </DialogTitle>
          </DialogHeader>
          {viewing ? (
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                {[
                  viewing.document_date,
                  place(viewing.source_location_id),
                  place(viewing.target_location_id),
                  viewing.counterparty,
                  viewing.note,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <ul className="divide-y divide-border">
                {viewing.lines.map((line, index) => (
                  <li className="flex justify-between gap-4 py-2" key={index}>
                    <span>{line.item_name}</span>
                    <span className="text-right">
                      {amount(line.quantity)}
                      {line.unit_price_minor !== null &&
                      line.unit_price_minor !== undefined
                        ? ` × ${money(line.unit_price_minor)}`
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
