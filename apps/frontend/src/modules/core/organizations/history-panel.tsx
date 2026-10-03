"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  getSettingsSchema,
  readCatalogDictionary,
  readOrganizationHistory,
  type CatalogDictionary,
  type HistoryEntry,
  type HistoryPage,
  type SettingOption,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  type ColumnDef,
  type DataTableQuery,
} from "@saas-core/ui/components/data-table";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";

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
/** `group`: only the changes of one settings group (its „Historia zmian” link). */
export function HistoryPanel({ group }: { group?: string } = {}) {
  const t = useTranslations("History");
  const locale = useLocale();
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
  // A category and a town are recorded by their keys; the catalogue's
  // dictionary gives them their names (UX-055). No catalogue, no names.
  const [dictionary, setDictionary] = useState<CatalogDictionary>();
  // A setting is recorded by its key; its form's own words name it here
  // (UX-055), for a product's settings too.
  const [settings, setSettings] = useState<Map<string, SettingOption>>();

  useEffect(() => {
    let active = true;
    readCatalogDictionary().then(
      (next) => {
        if (active) setDictionary(next);
      },
      () => undefined,
    );
    getSettingsSchema().then(
      (schema) => {
        if (active)
          setSettings(
            new Map(
              schema.groups.flatMap((item) =>
                item.keys.map((setting) => [setting.key, setting]),
              ),
            ),
          );
      },
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setPage(
        await readOrganizationHistory({
          page: query.pageIndex + 1,
          pageSize: query.pageSize,
          action,
          group,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [query.pageIndex, query.pageSize, action, group]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on query change
    void load();
  }, [load]);

  const actionLabel = (key: string) =>
    t.has(`actions.${messageKey(key)}`)
      ? t(`actions.${messageKey(key)}`)
      : humanize(key);
  const actingLabel = (via: string) =>
    t.has(`acting_${via}`) ? t(`acting_${via}`) : humanize(via);
  const language = locale === "en" ? "en" : "pl";
  // A settings change names its group in the target and its field in the
  // change (ADR-078 pkt 9).
  const setting = (entry: HistoryEntry, field: string) =>
    settings?.get(`${entry.target_type}.${field}`);
  const fieldLabel = (entry: HistoryEntry, key: string) =>
    setting(entry, key)?.label[language] ??
    (t.has(`fields.${key}`) ? t(`fields.${key}`) : humanize(key));
  const value = (
    raw: unknown,
    field?: string,
    entry?: HistoryEntry,
  ): string => {
    if (raw === null || raw === undefined || raw === "") return t("empty");
    if (typeof raw === "boolean") return raw ? t("yes") : t("no");
    if (Array.isArray(raw))
      return (
        raw.map((item) => value(item, field, entry)).join(", ") || t("empty")
      );
    // One of a setting's choices: what its form calls it.
    const choice =
      entry && field
        ? setting(entry, field)?.values?.find((item) => item.value === raw)
        : undefined;
    if (choice) return choice.label[language];
    // An amount is recorded in grosze.
    if (typeof raw === "number" && field?.endsWith("_minor"))
      return new Intl.NumberFormat(locale, {
        minimumFractionDigits: 2,
      }).format(raw / 100);
    // A text per language (`localized_text`): each language with its text.
    if (typeof raw === "object")
      return (
        Object.entries(raw as Record<string, unknown>)
          .map(([code, item]) => `${code}: ${value(item)}`)
          .join("; ") || t("empty")
      );
    if (field === "category")
      return (
        dictionary?.categories.find((item) => item.key === raw)?.labels[
          language
        ] ?? String(raw)
      );
    if (field === "city_slug" || field === "city")
      return (
        dictionary?.cities.find((item) => item.slug === raw)?.name ??
        String(raw)
      );
    return String(raw);
  };

  const targetText = (target: NonNullable<HistoryEntry["target"]>) =>
    target.at
      ? `${target.label} · ${formatDateTime(target.at, locale)}`
      : target.label;

  const columns: ColumnDef<HistoryEntry, unknown>[] = [
    {
      id: "when",
      header: t("when"),
      enableSorting: false,
      cell: ({ row: { original: entry } }) => (
        <time dateTime={entry.occurred_at} className="font-medium">
          {formatDateTime(entry.occurred_at, locale)}
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
          {entry.acting ? (
            // The person's membership acted through the assistant or a
            // translation job — not the person by hand (ADR-076 §6).
            <Badge variant="outline">{actingLabel(entry.acting.via)}</Badge>
          ) : entry.channel && entry.channel !== "panel" ? (
            // The panel is the usual way; only another one is worth a word
            // (UX-055).
            <Badge variant="outline">{t(`channel_${entry.channel}`)}</Badge>
          ) : null}
        </div>
      ),
    },
    {
      id: "what",
      header: t("what"),
      enableSorting: false,
      // On a phone the card is titled by what happened, not by when (UX-009).
      meta: { primary: true, className: "max-md:order-first" },
      cell: ({ row: { original: entry } }) => (
        <div className="space-y-1">
          <p className="font-medium wrap-anywhere">
            {actionLabel(entry.action)}
            {/* Which one: „Dodano gospodarstwo: Ferma Pod Lasem” (UX-055). */}
            {entry.target ? (
              <>
                {": "}
                {entry.target.href ? (
                  <Link
                    className="text-primary hover:underline"
                    href={entry.target.href}
                  >
                    {targetText(entry.target)}
                  </Link>
                ) : (
                  targetText(entry.target)
                )}
              </>
            ) : null}
          </p>
          <Changes
            entry={entry}
            fieldLabel={(field) => fieldLabel(entry, field)}
            value={(raw, field) => value(raw, field, entry)}
          />
          {entry.action === "privacy.retention.run" ? (
            <RetentionRun details={entry.details} />
          ) : null}
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
  value: (raw: unknown, field?: string) => string;
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
                : `${value(change.from, field)} → ${value(change.to, field)}`
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

/** What a retention run removed: which data, after how long and how many —
 *  never a person. The API words the period as the command's report does:
 *  „24 mies.”, „90 dni”. */
function RetentionRun({ details }: { details: HistoryEntry["details"] }) {
  const t = useTranslations("History");
  const { sweep, period, removed } = details as {
    sweep?: string;
    period?: string;
    removed?: number;
  };
  if (!sweep || typeof removed !== "number") return null;
  const kind = `retention.kinds.${messageKey(sweep)}`;
  const [, length, unit] = /^(\d+) (mies\.|dni)$/.exec(period ?? "") ?? [];
  return (
    <p className="text-sm text-muted-foreground wrap-anywhere">
      {t("retention.run", {
        kind: t.has(kind) ? t(kind) : humanize(sweep),
        period: length
          ? t(unit === "dni" ? "retention.days" : "retention.months", {
              count: Number(length),
            })
          : (period ?? t("empty")),
        count: removed,
      })}
    </p>
  );
}
