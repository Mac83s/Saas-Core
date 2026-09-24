"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
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
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { PanelPage } from "#components/panel/panel-page";
import {
  Combobox,
  ComboboxInput,
  ComboboxContent,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
} from "@saas-core/ui/components/combobox";

const terminal = new Set(["completed", "partial", "failed", "cancelled"]);
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function SeoAuditsPanel() {
  const t = useTranslations("SeoAudits");
  const nav = useTranslations("DashboardNav");
  const locale = useLocale();
  const [orders, setOrders] = useState<SeoAuditSummary[]>([]);
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [offer, setOffer] = useState<SeoAuditOffer>();
  const [selected, setSelected] = useState<SeoAuditOrder>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [orderProblem, setOrderProblem] = useState<string>();
  const [issueLimit, setIssueLimit] = useState(100);
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
      if (history.status === "fulfilled") {
        setOrders(history.value.items);
        setNextCursor(history.value.next_cursor);
      } else {
        setOrders([]);
        setSelected(undefined);
        setNextCursor(null);
        setProblem(errorText(history.reason));
      }
      if (siteList.status === "fulfilled") setSites(siteList.value.items);
      else setSites([]);
      if (!receipt.current) {
        if (quote.status === "fulfilled") setOffer(quote.value);
        else setOffer(undefined);
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
      setIssueLimit(100);
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
      setIssueLimit(100);
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

  return (
    <div className="space-y-8">
      <PanelPage
        actions={
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
        }
        description={t("description")}
        eyebrow={nav("website")}
        title={t("title")}
      />
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
      ) : !loading ? (
        <p className="text-sm text-muted-foreground">
          {sites.length ? t("orderingUnavailable") : t("noSites")}
        </p>
      ) : null}
      <section aria-labelledby="seo-history" className="space-y-4">
        <h2 id="seo-history" className="text-xl font-semibold">
          {t("history")}
        </h2>
        {!loading && !orders.length ? <p>{t("empty")}</p> : null}
        <ul className="space-y-3">
          {orders.map((order) => (
            <li
              key={order.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
            >
              <div>
                <p className="font-medium">{siteName(order.site_id)}</p>
                <p className="text-sm text-muted-foreground">
                  {time(order.created_at)} · {t(`states.${order.state}`)}
                </p>
                <p className="text-sm">
                  {t(`credits.${order.credit_state}`, {
                    count: order.credit_cost,
                  })}
                </p>
              </div>
              <Button variant="outline" onClick={() => void inspect(order)}>
                {t("openReport")}
              </Button>
            </li>
          ))}
        </ul>
        {nextCursor ? (
          <Button variant="outline" onClick={() => void older()}>
            {t("older")}
          </Button>
        ) : null}
      </section>
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
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">{t("issues")}</caption>
                    <thead>
                      <tr>
                        <th className="p-3">{t("severity")}</th>
                        <th className="p-3">{t("check")}</th>
                        <th className="p-3">{t("page")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {issues.slice(0, issueLimit).map((issue, index) => (
                        <tr
                          key={typeof issue.id === "string" ? issue.id : index}
                          className="border-t"
                        >
                          <td className="p-3">
                            {typeof issue.severity === "string" &&
                            [
                              "critical",
                              "high",
                              "medium",
                              "low",
                              "info",
                            ].includes(issue.severity)
                              ? t(`severityLabels.${issue.severity}`)
                              : "—"}
                          </td>
                          <td className="p-3">
                            {typeof issue.rule_code === "string"
                              ? issue.rule_code
                              : "—"}
                          </td>
                          <td className="max-w-lg break-all p-3">
                            {typeof issue.page_url === "string"
                              ? issue.page_url
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {issues.length > issueLimit ? (
                  <Button
                    variant="outline"
                    onClick={() => setIssueLimit((value) => value + 100)}
                  >
                    {t("moreIssues")}
                  </Button>
                ) : null}
              </>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
