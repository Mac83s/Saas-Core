"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";

import {
  readOrganizationHistory,
  type HistoryEntry,
  type HistoryPage,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  type ColumnDef,
  type DataTableQuery,
} from "@saas-core/ui/components/data-table";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useDataTableLabels } from "#lib/data-table-labels";

const PAGE_SIZE = 25;

/** next-intl nests on dots, and action keys are dotted: `sites.page.created`. */
function messageKey(key: string): string {
  return key.replaceAll(".", "_");
}

/** An unknown key still reads as words rather than as an identifier. */
function humanize(key: string): string {
  return key.replaceAll(/[._]+/g, " ");
}

/**
 * The organization's history of changes (ADR-054 list, server mode): who did
 * what, when, through which channel, and what a field was before and after.
 * A product adds labels for its own actions under `History.actions`.
 */
export function HistoryPanel() {
  const t = useTranslations("History");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [query, setQuery] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
    sorting: [],
    search: "",
  });
  const [action, setAction] = useState("");
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setPage(
        await readOrganizationHistory({
          page: query.pageIndex + 1,
          pageSize: query.pageSize,
          action,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [query.pageIndex, query.pageSize, action]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on query change
    void load();
  }, [load]);

  const actionLabel = (key: string) =>
    t.has(`actions.${messageKey(key)}`)
      ? t(`actions.${messageKey(key)}`)
      : humanize(key);
  const fieldLabel = (key: string) =>
    t.has(`fields.${key}`) ? t(`fields.${key}`) : humanize(key);
  const value = (raw: unknown): string => {
    if (raw === null || raw === undefined || raw === "") return t("empty");
    if (typeof raw === "boolean") return raw ? t("yes") : t("no");
    if (Array.isArray(raw)) return raw.map(value).join(", ") || t("empty");
    return String(raw);
  };

  const columns: ColumnDef<HistoryEntry, unknown>[] = [
    {
      id: "when",
      header: t("when"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: entry } }) => (
        <time dateTime={entry.occurred_at} className="font-medium">
          {format.dateTime(new Date(entry.occurred_at), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </time>
      ),
    },
    {
      id: "who",
      header: t("who"),
      enableSorting: false,
      cell: ({ row: { original: entry } }) => (
        <div className="space-y-1">
          <p className="wrap-anywhere">
            {entry.actor?.name ??
              (entry.channel === "api_key" ? t("apiKey") : t("system"))}
          </p>
          {entry.channel ? (
            <Badge variant="outline">{t(`channel_${entry.channel}`)}</Badge>
          ) : null}
        </div>
      ),
    },
    {
      id: "what",
      header: t("what"),
      enableSorting: false,
      cell: ({ row: { original: entry } }) => (
        <div className="space-y-1">
          <p className="font-medium">{actionLabel(entry.action)}</p>
          <Changes entry={entry} fieldLabel={fieldLabel} value={value} />
        </div>
      ),
    },
  ];

  if (failed && !page) {
    return (
      <div className="flex flex-wrap items-center gap-3" role="alert">
        <p className="text-sm text-destructive">{t("loadError")}</p>
        <Button onClick={() => void load()} variant="outline">
          {t("retry")}
        </Button>
      </div>
    );
  }

  return (
    <DataTable
      caption={t("caption")}
      columns={columns}
      data={page?.items ?? []}
      getRowId={(entry) => entry.id}
      labels={{ ...labels, empty: t("none") }}
      loading={loading}
      onQueryChange={setQuery}
      query={query}
      rowCount={page?.total ?? 0}
      toolbar={
        <label className="flex w-full flex-wrap items-center gap-2 text-sm sm:w-auto sm:flex-nowrap">
          <span className="text-muted-foreground">{t("filter")}</span>
          {/* NativeSelect fills its parent; the parent sets the width. */}
          <span className="w-full sm:w-64">
            <NativeSelect
              onChange={(event) => {
                setAction(event.target.value);
                setQuery((current) => ({ ...current, pageIndex: 0 }));
              }}
              value={action}
            >
              <option value="">{t("allActions")}</option>
              {(page?.actions ?? []).map((key) => (
                <option key={key} value={key}>
                  {actionLabel(key)}
                </option>
              ))}
            </NativeSelect>
          </span>
        </label>
      }
    />
  );
}

/** Before → after for each changed field; a private field says only that it
 *  changed; older rows name the fields without values. */
function Changes({
  entry,
  fieldLabel,
  value,
}: {
  entry: HistoryEntry;
  fieldLabel: (key: string) => string;
  value: (raw: unknown) => string;
}) {
  const t = useTranslations("History");
  const changes = Object.entries(entry.changes ?? {}) as [
    string,
    { from?: unknown; to?: unknown; changed?: boolean },
  ][];
  if (changes.length > 0) {
    return (
      <ul className="space-y-0.5 text-sm text-muted-foreground">
        {changes.map(([field, change]) => (
          <li key={field} className="wrap-anywhere">
            {`${fieldLabel(field)}: ${
              change.changed
                ? t("changedPrivate")
                : `${value(change.from)} → ${value(change.to)}`
            }`}
          </li>
        ))}
      </ul>
    );
  }
  if (entry.changed_fields.length > 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("changedFields", {
          fields: entry.changed_fields.map(fieldLabel).join(", "),
        })}
      </p>
    );
  }
  return null;
}
