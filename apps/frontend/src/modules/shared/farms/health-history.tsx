"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { useFormatter, useTranslations } from "next-intl";
import { PencilIcon, Undo2Icon } from "lucide-react";

import {
  correctFarmAnimalHealth,
  type FarmAnimalHealthEntry,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { useDataTableLabels } from "#lib/data-table-labels";
import { EntryPhoto } from "./entry-photo";
import { farmProblem } from "./problem";
import { Withdrawal } from "./withdrawal";

/** `HealthEntryKind` of the register (models.py). A vertical says what it did
 * in `source` and `details`; the register only shows the kind. */
export const ENTRY_KINDS = [
  "note",
  "alert",
  "treatment",
  "medication",
  "visit",
] as const;

/** What the register itself writes: an entry added here by hand. Anything
 * else is corrected in the module that wrote it (ADR-062). */
const MANUAL_SOURCE = "farms.manual";

type Entry = FarmAnimalHealthEntry;
type Lineage = { current: Entry; older: Entry[] };
type Correction = {
  id: string;
  mode: "replace" | "withdraw";
  /** The action that opened the form; focus goes back to it. */
  trigger: HTMLElement | null;
};

/** The revisions of one entry share its source and reference. */
const lineKey = (entry: Entry) => `${entry.source}|${entry.source_reference}`;

/**
 * One entry and its revisions: the one in force on top, the ones it replaced
 * behind „historia” (answer 2A of 28.09). The feed comes newest first, so the
 * first revision met of a line is where the line stands in the list.
 */
function lineages(entries: Entry[]): Lineage[] {
  const lines = new Map<string, Entry[]>();
  for (const entry of entries) {
    const key = lineKey(entry);
    lines.set(key, [...(lines.get(key) ?? []), entry]);
  }
  return [...lines.values()].map((revisions) => {
    const ordered = [...revisions].sort((a, b) => b.revision - a.revision);
    const current =
      ordered.find((entry) => entry.retracted_at === null) ?? ordered[0]!;
    return {
      current,
      older: ordered.filter((entry) => entry !== current),
    };
  });
}

/**
 * The animal's file (ADR-054 list, client mode): one row per entry, its older
 * revisions nested in the row. Nothing written is changed or removed (owner,
 * 28.09): „Popraw” and „Wycofaj” write the next revision of an entry, and only
 * its author's organization may — a keeper who disagrees with a company's
 * entry adds a note of their own. The filters in `toolbar` ask the server.
 */
export function HealthHistory({
  animalId,
  entries,
  loading,
  toolbar,
  canManage,
  onChanged,
}: {
  animalId: string;
  entries: Entry[];
  loading: boolean;
  toolbar: ReactNode;
  canManage: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("Animals");
  const common = useTranslations("Common");
  const format = useFormatter();
  const labels = useDataTableLabels();
  // One correction at a time, opened in its entry's row.
  const [correcting, setCorrecting] = useState<Correction>();
  const lines = lineages(entries);

  const correctable = (entry: Entry) =>
    canManage &&
    !entry.author_is_external &&
    entry.source === MANUAL_SOURCE &&
    entry.retracted_at === null &&
    !entry.details?.withdrawn;
  const close = () => {
    correcting?.trigger?.focus();
    setCorrecting(undefined);
  };

  const columns: ColumnDef<Lineage, unknown>[] = [
    {
      id: "entry",
      accessorFn: (line) => line.current.summary,
      header: t("entryColumn"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: line } }) => (
        <>
          <EntryView byline={false} entry={line.current} />
          {correcting?.id === line.current.id ? (
            <CorrectionForm
              animalId={animalId}
              entry={line.current}
              key={correcting.mode}
              mode={correcting.mode}
              onCancel={close}
              onSaved={() => {
                close();
                onChanged();
              }}
            />
          ) : null}
          {line.older.length > 0 ? (
            <Revisions
              entries={line.older}
              id={`entry-history-${line.current.id}`}
            />
          ) : null}
        </>
      ),
    },
    {
      id: "date",
      accessorFn: (line) => line.current.occurred_on,
      header: t("entryDate"),
      cell: ({ row: { original: line } }) => (
        <span className="tabular-nums">
          {format.dateTime(new Date(line.current.occurred_on), {
            dateStyle: "medium",
          })}
        </span>
      ),
    },
    {
      id: "author",
      accessorFn: (line) => line.current.author_name,
      header: t("entryAuthor"),
      cell: ({ row: { original: line } }) => (
        <>
          <p className="wrap-anywhere">{line.current.author_name || "—"}</p>
          {line.current.author_is_external ? (
            <p className="text-xs text-muted-foreground wrap-anywhere">
              {line.current.author_organization_name}
            </p>
          ) : null}
        </>
      ),
    },
    ...(lines.some((line) => correctable(line.current))
      ? [
          {
            id: "actions",
            header: t("actions"),
            meta: { actions: true },
            cell: ({ row: { original: line } }) => (
              <RowActions
                items={
                  correctable(line.current)
                    ? [
                        // Correcting is the entry's edit: always in sight.
                        {
                          label: t("entryCorrect"),
                          icon: <PencilIcon aria-hidden="true" />,
                          inline: true,
                          onSelect: (trigger: HTMLElement | null) =>
                            setCorrecting({
                              id: line.current.id,
                              mode: "replace",
                              trigger,
                            }),
                        },
                        {
                          label: t("entryWithdraw"),
                          icon: <Undo2Icon aria-hidden="true" />,
                          destructive: true,
                          onSelect: (trigger: HTMLElement | null) =>
                            setCorrecting({
                              id: line.current.id,
                              mode: "withdraw",
                              trigger,
                            }),
                        },
                      ]
                    : []
                }
                label={t("entryActionsFor", { summary: line.current.summary })}
              />
            ),
          } satisfies ColumnDef<Lineage, unknown>,
        ]
      : []),
  ];

  return (
    <DataTable
      caption={t("historyCaption")}
      columns={columns}
      data={lines}
      getRowId={(line) => lineKey(line.current)}
      labels={{ ...labels, empty: t("noHistory"), loading: common("loading") }}
      loading={loading}
      toolbar={toolbar}
    />
  );
}

/** The versions an entry replaced, behind „historia”, struck through. */
function Revisions({ entries, id }: { entries: Entry[]; id: string }) {
  const t = useTranslations("Animals");
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="mt-2">
        <Button
          aria-controls={id}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          size="sm"
          variant="ghost"
        >
          {t("entryHistory", { count: entries.length })}
        </Button>
      </div>
      {open ? (
        <ol className="mt-3 space-y-2 border-l-2 pl-3" id={id}>
          {entries.map((entry) => (
            <li className="rounded-lg border border-dashed p-2" key={entry.id}>
              <EntryView entry={entry} />
            </li>
          ))}
        </ol>
      ) : null}
    </>
  );
}

/** An entry's words and marks; `byline` adds when and by whom, which a row of
 * the list shows in its own columns. */
function EntryView({
  entry,
  byline = true,
}: {
  entry: Entry;
  byline?: boolean;
}) {
  const t = useTranslations("Animals");
  const format = useFormatter();
  const date = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium" });
  const moment = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  const withdrawn = Boolean(entry.details?.withdrawn);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{t(`kind_${entry.kind}`)}</Badge>
        {entry.private ? (
          <Badge variant="outline">{t("entryPrivateBadge")}</Badge>
        ) : null}
        {/* A replaced entry stays, struck through, next to the correction
            that says why (ADR-062). */}
        {entry.retracted_at ? (
          <Badge variant="outline">
            {t("entryRetracted", { date: moment(entry.retracted_at) })}
          </Badge>
        ) : null}
        {withdrawn ? (
          <Badge variant="outline">{t("entryWithdrawn")}</Badge>
        ) : entry.corrects_id ? (
          <Badge variant="outline">{t("entryCorrection")}</Badge>
        ) : entry.correction_reason ? (
          <Badge variant="outline">{t("entryAddition")}</Badge>
        ) : null}
      </div>
      <p
        className={
          entry.retracted_at || withdrawn
            ? "mt-1 text-sm text-muted-foreground line-through"
            : "mt-1 text-sm"
        }
      >
        {entry.summary}
      </p>
      {entry.retracted_at || withdrawn ? null : (
        <Withdrawal
          meat={entry.withdrawal_meat_until}
          milk={entry.withdrawal_milk_until}
          plain
        />
      )}
      {entry.correction_reason ? (
        <p className="mt-1 text-sm">
          {entry.corrected_by
            ? t("correctionReasonBy", {
                reason: entry.correction_reason,
                name: entry.corrected_by,
              })
            : t("correctionReason", { reason: entry.correction_reason })}
        </p>
      ) : null}
      {entry.photos.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {entry.photos.map((photo) => (
            <EntryPhoto entryId={entry.id} key={photo} mediaId={photo} />
          ))}
        </div>
      ) : null}
      {byline ? (
        <p className="text-xs text-muted-foreground">
          {[
            date(entry.occurred_on),
            entry.author_name,
            entry.author_is_external ? entry.author_organization_name : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
    </>
  );
}

function CorrectionForm({
  animalId,
  entry,
  mode,
  onCancel,
  onSaved,
}: {
  animalId: string;
  entry: Entry;
  mode: "replace" | "withdraw";
  onCancel: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("Animals");
  const [kind, setKind] = useState<string>(entry.kind);
  const [summary, setSummary] = useState(entry.summary);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  // Somebody else may have read it: the reason is theirs to know (1A).
  const reasonRequired = !entry.private;
  const ready =
    (!reasonRequired || reason.trim() !== "") &&
    (mode === "withdraw" || summary.trim() !== "");
  const prefix = `correct-${entry.id}`;
  // The form opens in the entry's cell, away from the action that asked for
  // it; its first field takes focus so the keyboard lands where work goes on.
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    form.current?.querySelector<HTMLElement>("select, textarea")?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setProblem(undefined);
    try {
      await correctFarmAnimalHealth(animalId, entry.id, {
        action: mode,
        reason: reason.trim(),
        // A withdrawal keeps the entry's words; the server ignores these.
        summary: mode === "replace" ? summary.trim() : "",
        ...(mode === "replace"
          ? { kind: kind as (typeof ENTRY_KINDS)[number] }
          : {}),
      });
      onSaved();
    } catch (error) {
      setProblem(farmProblem(error, t("correctionFailed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="mt-3 space-y-3 rounded-lg border p-3"
      onSubmit={submit}
      ref={form}
    >
      <p className="text-sm text-muted-foreground">
        {mode === "replace" ? t("correctHint") : t("withdrawHint")}
      </p>
      {mode === "replace" ? (
        <>
          <Field>
            <FieldLabel htmlFor={`${prefix}-kind`}>{t("kind")}</FieldLabel>
            <NativeSelect
              id={`${prefix}-kind`}
              onChange={(event) => setKind(event.target.value)}
              value={kind}
            >
              {ENTRY_KINDS.map((value) => (
                <option key={value} value={value}>
                  {t(`kind_${value}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor={`${prefix}-summary`}>
              {t("entrySummary")}
            </FieldLabel>
            <Input
              id={`${prefix}-summary`}
              maxLength={240}
              onChange={(event) => setSummary(event.target.value)}
              required
              value={summary}
            />
          </Field>
        </>
      ) : null}
      <Field>
        <FieldLabel htmlFor={`${prefix}-reason`}>
          {reasonRequired
            ? t("correctionReasonLabel")
            : t("correctionReasonOptional")}
        </FieldLabel>
        <Textarea
          id={`${prefix}-reason`}
          maxLength={240}
          onChange={(event) => setReason(event.target.value)}
          required={reasonRequired}
          value={reason}
        />
      </Field>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={!ready || busy} size="sm" type="submit">
          {mode === "replace" ? t("correctSave") : t("withdrawSave")}
        </Button>
        <Button onClick={onCancel} size="sm" type="button" variant="ghost">
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}
