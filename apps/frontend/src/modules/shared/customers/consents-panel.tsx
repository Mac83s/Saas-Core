"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Undo2Icon } from "lucide-react";

import {
  ApiProblemError,
  listMarketingConsents,
  withdrawMarketingConsent,
  type MarketingConsent,
  type MarketingConsentPage,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
  type DataTableQuery,
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

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";

const PAGE_SIZE = 25;
type State = "granted" | "withdrawn";

/**
 * Ustawienia › Zgody marketingowe (ADR-073 §9): who agreed to receive the
 * company's offers and promotions, read from the consent journal — when, on
 * which form and to which words. Nothing is edited here: a withdrawal the
 * customer asked for is written down as the journal's next line.
 */
export function MarketingConsentsPanel({
  canManage = false,
}: {
  /** May write a withdrawal down (`customers.manage`). */
  canManage?: boolean;
}) {
  const t = useTranslations("MarketingConsents");
  const common = useTranslations("Common");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [query, setQuery] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
    sorting: [],
    search: "",
  });
  const [state, setState] = useState<State>("granted");
  const [page, setPage] = useState<MarketingConsentPage>();
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [withdrawing, setWithdrawing] = useState<MarketingConsent>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [notice, setNotice] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setPage(
        await listMarketingConsents({
          state,
          page: query.pageIndex + 1,
          pageSize: query.pageSize,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [query.pageIndex, query.pageSize, state]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on query change
    void load();
  }, [load]);

  async function withdraw(row: MarketingConsent) {
    setBusy(true);
    setProblem(undefined);
    try {
      await withdrawMarketingConsent(row.customer_id, row.consent_id);
      setWithdrawing(undefined);
      setNotice(t("withdrawn", { name: row.name }));
      await load();
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "consent_changed"
      ) {
        // Somebody was faster, or the customer agreed again: read it anew.
        setWithdrawing(undefined);
        setNotice(t("changed"));
        await load();
      } else setProblem(t("withdrawFailed"));
    } finally {
      setBusy(false);
    }
  }

  const source = (value: string) =>
    t.has(`sources.${value.replaceAll(".", "_")}`)
      ? t(`sources.${value.replaceAll(".", "_")}`)
      : value;

  const columns: ColumnDef<MarketingConsent, unknown>[] = [
    {
      id: "customer",
      header: t("colCustomer"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-medium wrap-anywhere">{row.name}</span>
          {row.email ? (
            <a
              className="text-sm text-primary hover:underline"
              href={`mailto:${row.email}`}
            >
              {row.email}
            </a>
          ) : null}
          {row.phone ? (
            <span className="text-sm text-muted-foreground">{row.phone}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "when",
      header: t("colWhen"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-col gap-0.5">
          <span>{formatDateTime(row.consented_at, locale)}</span>
          <span className="text-sm text-muted-foreground">
            {source(row.source)}
            {row.locale ? ` · ${row.locale.toUpperCase()}` : ""}
          </span>
        </span>
      ),
    },
    {
      id: "wording",
      header: t("colWording"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.wording ? (
          <span className="wrap-anywhere">„{row.wording}”</span>
        ) : (
          <span className="text-muted-foreground">{t("wordingUnknown")}</span>
        ),
    },
    {
      id: "state",
      header: t("colState"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.granted ? (
          <Badge variant="secondary">{t("states.granted")}</Badge>
        ) : (
          <span className="flex flex-col gap-0.5">
            <Badge variant="outline">{t("states.withdrawn")}</Badge>
            {row.withdrawn_at ? (
              <span className="text-sm text-muted-foreground">
                {formatDateTime(row.withdrawn_at, locale)}
              </span>
            ) : null}
          </span>
        ),
    },
    ...(canManage && state === "granted"
      ? [
          {
            id: "actions",
            header: t("colActions"),
            meta: { actions: true },
            cell: ({ row: { original: row } }) => (
              <RowActions
                items={[
                  {
                    label: t("withdraw"),
                    onSelect: () => {
                      setProblem(undefined);
                      setWithdrawing(row);
                    },
                    inline: true,
                    icon: <Undo2Icon aria-hidden="true" />,
                  },
                ]}
                label={t("actionsFor", { name: row.name })}
              />
            ),
          } satisfies ColumnDef<MarketingConsent, unknown>,
        ]
      : []),
  ];

  return (
    <PanelPage description={t("description")} title={t("title")}>
      {notice ? (
        <p className="text-sm text-muted-foreground" role="status">
          {notice}
        </p>
      ) : null}
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <DataTable
          caption={t("caption")}
          columns={columns}
          data={page?.items ?? []}
          getRowId={(row) => row.customer_id}
          labels={{
            ...labels,
            empty: state === "granted" ? t("empty") : t("emptyWithdrawn"),
          }}
          loading={loading}
          onQueryChange={setQuery}
          pageSize={PAGE_SIZE}
          query={query}
          rowCount={page?.total ?? 0}
          // The page's scope, not a filter: it stays over an empty list, so
          // whoever withdrew the last consent can still read who took theirs
          // back.
          toolbar={
            <DataTableFilter
              id="consents-state"
              label={t("filterState")}
              onChange={(event) => {
                setState(event.target.value as State);
                setQuery((current) => ({ ...current, pageIndex: 0 }));
              }}
              value={state}
            >
              <option value="granted">{t("states.granted")}</option>
              <option value="withdrawn">{t("states.withdrawn")}</option>
            </DataTableFilter>
          }
        />
      )}
      <p className="text-sm text-muted-foreground">{t("removedNote")}</p>
      {withdrawing ? (
        <Dialog
          onOpenChange={(open) => {
            if (!open) setWithdrawing(undefined);
          }}
          open
        >
          <DialogContent closeLabel={common("close")}>
            <DialogHeader>
              <DialogTitle>
                {t("withdrawTitle", { name: withdrawing.name })}
              </DialogTitle>
              <DialogDescription>{t("withdrawHint")}</DialogDescription>
            </DialogHeader>
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            <DialogFooter>
              <DialogClose render={<Button type="button" variant="outline" />}>
                {common("cancel")}
              </DialogClose>
              <Button
                disabled={busy}
                onClick={() => void withdraw(withdrawing)}
                type="button"
              >
                {t("withdrawConfirm")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </PanelPage>
  );
}
