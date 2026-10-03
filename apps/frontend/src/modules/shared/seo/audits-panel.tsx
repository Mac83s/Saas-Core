"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { FileTextIcon } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  ApiProblemError,
  getSeoAuditOffer,
  listSeoAudits,
  listSites,
  readSeoAudit,
  requestSeoAudit,
  type SeoAuditOffer,
  type SeoAuditOrder,
  type SeoAuditSummary,
  type SiteSummary,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { PlanGate } from "#components/panel/plan-gate";
import { SeoTabs } from "./seo-tabs";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  Combobox,
  ComboboxInput,
  ComboboxContent,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
} from "@saas-core/ui/components/combobox";

const terminal = new Set(["completed", "partial", "failed", "cancelled"]);
// Most severe first: sorting the column ascending puts critical on top.
const severities = ["critical", "high", "medium", "low", "info"];
type Issue = Record<string, unknown>;
function record(value: unknown): Issue {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Issue)
    : {};
}
function text(value: unknown): string {
  return typeof value === "string" ? value : "—";
}
/** The plan leaves audits out: a different thing from a failure. */
function unpaid(reason: unknown): boolean {
  return (
    reason instanceof ApiProblemError &&
    reason.problem.code === "entitlement_required"
  );
}
function refused(reason: unknown): boolean {
  return reason instanceof ApiProblemError && reason.problem.status === 403;
}

export function SeoAuditsPanel({
  canManageBilling = false,
}: {
  /** The owner may change the plan; everybody else asks them. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("SeoAudits");
  const nav = useTranslations("DashboardNav");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [orders, setOrders] = useState<SeoAuditSummary[]>([]);
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [offer, setOffer] = useState<SeoAuditOffer>();
  // Why there is no offer: not in the plan, not for this role, or failed.
  const [noOffer, setNoOffer] = useState<"plan" | "role" | "failed">();
  // No history at all in the plan: no table, no refresh, only the way out.
  const [planless, setPlanless] = useState(false);
  const [selected, setSelected] = useState<SeoAuditOrder>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [orderProblem, setOrderProblem] = useState<string>();
  const busy = useRef(false);
  const receipt = useRef<{ fingerprint: string; key: string } | undefined>(
    undefined,
  );
  const schema = useMemo(
    () => z.object({ siteId: z.string().min(1, t("chooseSite")) }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { siteId: "" },
  });
  const chosenSiteId = useWatch({ control: form.control, name: "siteId" });

  const errorText = useCallback(
    (error: unknown) => {
      if (error instanceof ApiProblemError) {
        if (error.problem.code === "credit_price_changed")
          return t("priceChanged");
        if (error.problem.code === "credits_exhausted")
          return t("creditsExhausted");
        if (error.problem.status === 403) return t("accessUnavailable");
        if (error.problem.status === 503) return t("unavailable");
        if (typeof error.problem.detail === "string")
          return error.problem.detail;
      }
      return t("loadError");
    },
    [t],
  );

  const remember = useCallback((order: SeoAuditOrder) => {
    setSelected(order);
    setOrders((rows) =>
      [order, ...rows.filter((row) => row.id !== order.id)].sort((a, b) =>
        b.id.localeCompare(a.id),
      ),
    );
  }, []);

  const load = useCallback(() => {
    return Promise.allSettled([
      listSeoAudits(),
      listSites(),
      getSeoAuditOffer(),
    ]).then(([history, siteList, quote]) => {
      setProblem(undefined);
      setPlanless(history.status === "rejected" && unpaid(history.reason));
      if (history.status === "fulfilled") {
        setOrders(history.value.items);
        setNextCursor(history.value.next_cursor);
      } else {
        setOrders([]);
        setSelected(undefined);
        setNextCursor(null);
        if (!unpaid(history.reason)) setProblem(errorText(history.reason));
      }
      if (siteList.status === "fulfilled") setSites(siteList.value.items);
      else setSites([]);
      if (!receipt.current) {
        if (quote.status === "fulfilled") setOffer(quote.value);
        else setOffer(undefined);
        setNoOffer(
          quote.status === "fulfilled"
            ? undefined
            : unpaid(quote.reason)
              ? "plan"
              : refused(quote.reason)
                ? "role"
                : "failed",
        );
      }
      setLoading(false);
    });
  }, [errorText]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!selected || terminal.has(selected.state)) return;
    let cancelled = false;
    const timer = setInterval(() => {
      readSeoAudit(selected.id)
        .then((order) => {
          if (!cancelled) remember(order);
        })
        .catch((error: unknown) => {
          if (!cancelled) setProblem(errorText(error));
        });
    }, 10_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [selected, remember, errorText]);

  async function submit(values: { siteId: string }) {
    if (busy.current || !offer) return;
    busy.current = true;
    setPending(true);
    setOrderProblem(undefined);
    const fingerprint = JSON.stringify([
      values.siteId,
      offer.credit_cost,
      offer.max_pages,
    ]);
    if (receipt.current?.fingerprint !== fingerprint)
      receipt.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const order = await requestSeoAudit({
        site_id: values.siteId,
        max_pages: offer.max_pages,
        expected_credit_cost: offer.credit_cost,
        idempotency_key: receipt.current.key,
      });
      remember(order);
      receipt.current = undefined;
      setUncertain(false);
    } catch (error) {
      const unknown =
        !(error instanceof ApiProblemError) || error.problem.status >= 500;
      setUncertain(unknown);
      if (!unknown) receipt.current = undefined;
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "credit_price_changed"
      ) {
        setOffer(undefined);
        try {
          setOffer(await getSeoAuditOffer());
        } catch {
          /* Keep ordering disabled without a quote. */
        }
        receipt.current = undefined;
      }
      setOrderProblem(unknown ? t("uncertainRequest") : errorText(error));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  async function inspect(order: SeoAuditSummary) {
    setProblem(undefined);
    try {
      remember(await readSeoAudit(order.id));
    } catch (error) {
      setProblem(errorText(error));
    }
  }

  async function older() {
    if (!nextCursor) return;
    try {
      const page = await listSeoAudits(nextCursor);
      setOrders((rows) => [
        ...rows,
        ...page.items.filter((item) => !rows.some((row) => row.id === item.id)),
      ]);
      setNextCursor(page.next_cursor);
    } catch (error) {
      setProblem(errorText(error));
    }
  }

  const snapshot = record(selected?.report_snapshot);
  const score = record(snapshot.score).overall_score;
  const issues = Array.isArray(snapshot.issues)
    ? snapshot.issues.map(record)
    : [];
  const observedAt = record(snapshot.provenance).observed_at;
  const siteName = (id: string) =>
    sites.find((site) => site.id === id)?.name ?? t("website");
  const time = (value: string) => new Date(value).toLocaleString(locale);
  const severity = (issue: Issue) =>
    typeof issue.severity === "string" && severities.includes(issue.severity)
      ? t(`severityLabels.${issue.severity}`)
      : "—";

  const orderColumns: ColumnDef<SeoAuditSummary, unknown>[] = [
    {
      id: "site",
      accessorFn: (order) => siteName(order.site_id),
      header: t("website"),
      meta: { primary: true },
      cell: ({ row: { original: order } }) => (
        <p className="font-medium wrap-anywhere">{siteName(order.site_id)}</p>
      ),
    },
    {
      id: "created",
      accessorKey: "created_at",
      header: t("ordered"),
      cell: ({ row: { original: order } }) => time(order.created_at),
    },
    {
      id: "state",
      accessorFn: (order) => t(`states.${order.state}`),
      header: t("state"),
    },
    {
      id: "credits",
      accessorFn: (order) =>
        t(`credits.${order.credit_state}`, { count: order.credit_cost }),
      header: t("creditsHeader"),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: order } }) => (
        <RowActions
          items={[
            {
              label: t("openReport"),
              icon: <FileTextIcon aria-hidden="true" />,
              inline: true,
              onSelect: () => void inspect(order),
            },
          ]}
          label={t("actionsFor", {
            name: `${siteName(order.site_id)}, ${time(order.created_at)}`,
          })}
        />
      ),
    },
  ];

  const issueColumns: ColumnDef<Issue, unknown>[] = [
    {
      id: "check",
      accessorFn: (issue) => text(issue.rule_code),
      header: t("check"),
      meta: { primary: true },
      cell: ({ row: { original: issue } }) => (
        <p className="font-medium wrap-anywhere">{text(issue.rule_code)}</p>
      ),
    },
    {
      id: "severity",
      // Sorts by rank, not by the word: critical before high before medium.
      accessorFn: (issue) => {
        const rank = severities.indexOf(String(issue.severity));
        return rank < 0 ? severities.length : rank;
      },
      header: t("severity"),
      cell: ({ row: { original: issue } }) => severity(issue),
    },
    {
      id: "page",
      accessorFn: (issue) => text(issue.page_url),
      header: t("page"),
      cell: ({ row: { original: issue } }) => (
        <span className="break-all">{text(issue.page_url)}</span>
      ),
    },
  ];

  return (
    <PanelPage
      actions={
        planless ? null : (
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => {
              setLoading(true);
              void load();
            }}
          >
            {t("refresh")}
          </Button>
        )
      }
      description={t("description")}
      eyebrow={nav("website")}
      title={t("title")}
    >
      <SeoTabs />
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {orderProblem ? (
        <p role="alert" className="text-destructive">
          {orderProblem}
        </p>
      ) : null}
      {loading ? <p role="status">{t("loading")}</p> : null}
      {offer && sites.length ? (
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>{t("orderTitle")}</h2>
            </CardTitle>
            <CardDescription>
              {t("offer", {
                credits: offer.credit_cost,
                pages: offer.max_pages,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={(event) => void form.handleSubmit(submit)(event)}
              className="space-y-4"
            >
              <Field>
                <FieldLabel htmlFor="seo-site">{t("website")}</FieldLabel>
                {sites.length > 20 ? (
                  <Combobox
                    items={sites}
                    itemToStringLabel={(item) => item.name}
                    itemToStringValue={(item) => item.id}
                    isItemEqualToValue={(item, value) => item.id === value.id}
                    value={
                      sites.find((site) => site.id === chosenSiteId) ?? null
                    }
                    onValueChange={(item) =>
                      form.setValue("siteId", item?.id ?? "", {
                        shouldValidate: true,
                      })
                    }
                  >
                    <ComboboxInput
                      id="seo-site"
                      disabled={pending || uncertain}
                      placeholder={t("chooseSite")}
                      aria-invalid={!!form.formState.errors.siteId}
                    />
                    <ComboboxContent>
                      <ComboboxEmpty>{t("noSites")}</ComboboxEmpty>
                      <ComboboxList>
                        {sites.map((site) => (
                          <ComboboxItem key={site.id} value={site}>
                            {site.name}
                          </ComboboxItem>
                        ))}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                ) : (
                  <NativeSelect
                    id="seo-site"
                    disabled={pending || uncertain}
                    aria-invalid={!!form.formState.errors.siteId}
                    {...form.register("siteId")}
                  >
                    <option value="">{t("chooseSite")}</option>
                    {sites.map((site) => (
                      <option key={site.id} value={site.id}>
                        {site.name}
                      </option>
                    ))}
                  </NativeSelect>
                )}
                <FieldError errors={[form.formState.errors.siteId]} />
              </Field>
              <p className="text-sm text-muted-foreground">
                {t("chargePolicy")}
              </p>
              <Button type="submit" disabled={pending}>
                {pending
                  ? t("ordering")
                  : t("orderButton", { credits: offer.credit_cost })}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : loading ? null : noOffer === "plan" ? (
        <PlanGate
          action={
            canManageBilling
              ? {
                  href: "/panel/settings/billing?feature=seo.audit.enabled",
                  label: t("planGateAction"),
                }
              : undefined
          }
          title={t("planGateTitle")}
        >
          {t(canManageBilling ? "planGateOwner" : "planGateMember")}
        </PlanGate>
      ) : (
        <p className="text-sm text-muted-foreground">
          {!sites.length
            ? t("noSites")
            : noOffer === "role"
              ? t("orderingNotForRole")
              : t("orderingUnavailable")}
        </p>
      )}
      {planless ? null : (
        <PanelSection title={t("history")}>
          <DataTable
            caption={t("history")}
            columns={orderColumns}
            data={orders}
            getRowId={(order) => order.id}
            labels={{ ...labels, empty: t("empty") }}
            loading={loading}
          />
          {nextCursor ? (
            <Button variant="outline" onClick={() => void older()}>
              {t("older")}
            </Button>
          ) : null}
        </PanelSection>
      )}
      {selected ? (
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>{t("resultTitle", { site: siteName(selected.site_id) })}</h2>
            </CardTitle>
            <CardDescription>{t(`states.${selected.state}`)}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {!terminal.has(selected.state) ? (
              <p role="status">
                {selected.state === "reconciling"
                  ? t("reconciling")
                  : t("inProgress")}
              </p>
            ) : null}
            {selected.state === "partial" ? <p>{t("partial")}</p> : null}
            {selected.state === "failed" || selected.state === "cancelled" ? (
              <p>{t("notDelivered")}</p>
            ) : null}
            {selected.report_hash ? (
              <>
                <div className="flex flex-wrap gap-8">
                  <p>
                    {t("score")}:{" "}
                    <strong>
                      {typeof score === "number" ? `${score}/100` : "—"}
                    </strong>
                  </p>
                  <p>{t("issueCount", { count: issues.length })}</p>
                </div>
                {typeof observedAt === "string" ? (
                  <p className="text-sm text-muted-foreground">
                    {t("snapshotAt", { date: time(observedAt) })}
                  </p>
                ) : null}
                <DataTable
                  caption={t("issues")}
                  columns={issueColumns}
                  data={issues}
                  // Another report starts on its first page.
                  key={selected.id}
                  labels={labels}
                  searchable={issues.length > 10}
                  searchText={(issue) =>
                    [
                      text(issue.rule_code),
                      text(issue.page_url),
                      severity(issue),
                    ].join(" ")
                  }
                />
              </>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </PanelPage>
  );
}
