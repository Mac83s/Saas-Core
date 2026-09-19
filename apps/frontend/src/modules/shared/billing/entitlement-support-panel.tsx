"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { RefreshCwIcon, ShieldCheckIcon, ShieldXIcon } from "lucide-react";

import {
  ApiProblemError,
  getEntitlementSupportReport,
  type EntitlementSupportItem,
  type EntitlementSupportReport,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";

type Evidence = {
  kind?: string;
  ref?: string;
  reason?: string;
  granted_by?: string;
  expires_at?: string | null;
  expired_at?: string;
  fallback_source?: { kind?: string; ref?: string } | null;
};
type Translator = ReturnType<typeof useTranslations<"BillingSupport">>;

export function EntitlementSupportPanel() {
  const t = useTranslations("BillingSupport");
  const locale = useLocale();
  const [report, setReport] = useState<EntitlementSupportReport>();
  const [selectedKey, setSelectedKey] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      const data = await getEntitlementSupportReport();
      setReport(data);
      setSelectedKey((current) =>
        data.items.some((item) => item.key === current)
          ? current
          : data.items[0]?.key,
      );
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError && error.problem.status === 403
          ? t("noAccess")
          : t("loadError"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void getEntitlementSupportReport()
      .then((data) => {
        if (!mounted) return;
        setReport(data);
        setSelectedKey(data.items[0]?.key);
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        setProblem(
          error instanceof ApiProblemError && error.problem.status === 403
            ? t("noAccess")
            : t("loadError"),
        );
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [t]);

  const selected = useMemo(
    () => report?.items.find((item) => item.key === selectedKey) ?? null,
    [report, selectedKey],
  );
  const allowed = report?.items.filter((item) => item.available).length ?? 0;

  if (problem) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            role="alert"
          >
            {problem}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard
          label={t("plan")}
          value={
            report?.snapshot?.plan_key
              ? `${report.snapshot.plan_key} v${report.snapshot.plan_version}`
              : t("missingSnapshot")
          }
        />
        <SummaryCard
          label={t("accessMode")}
          value={label(t, report?.snapshot?.access_mode ?? "unknown")}
        />
        <SummaryCard
          label={t("availableCount")}
          value={`${allowed}/${report?.items.length ?? 0}`}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>{t("decisionTitle")}</CardTitle>
              <CardDescription>{t("decisionDescription")}</CardDescription>
            </div>
            <Button
              disabled={loading}
              onClick={() => void load()}
              size="sm"
              variant="outline"
            >
              <RefreshCwIcon aria-hidden="true" />
              {t("refresh")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="entitlement-key">
              {t("chooseKey")}
            </label>
            <Combobox
              disabled={loading}
              isItemEqualToValue={(item, value) => item.key === value.key}
              itemToStringLabel={(item) => item.key}
              itemToStringValue={(item) => item.key}
              items={report?.items ?? []}
              onValueChange={(item) => setSelectedKey(item?.key)}
              value={selected}
            >
              <ComboboxInput
                className="w-full"
                id="entitlement-key"
                placeholder={t("search")}
                showClear
              />
              <ComboboxContent>
                <ComboboxEmpty>{t("empty")}</ComboboxEmpty>
                <ComboboxList>
                  {(report?.items ?? []).map((item) => (
                    <ComboboxItem key={item.key} value={item}>
                      <span className="flex-1 truncate font-mono text-xs">
                        {item.key}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {t(item.kind === "feature" ? "feature" : "quota")}
                      </span>
                    </ComboboxItem>
                  ))}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
          </div>

          {selected ? (
            <DecisionDetails item={selected} locale={locale} />
          ) : (
            <p className="text-sm text-muted-foreground">{t("choosePrompt")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DecisionDetails({
  item,
  locale,
}: {
  item: EntitlementSupportItem;
  locale: string;
}) {
  const t = useTranslations("BillingSupport");
  const evidence = asEvidence(item.evidence);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-4 rounded-lg border p-4">
        <div className="flex flex-wrap items-center gap-2">
          {item.available ? (
            <ShieldCheckIcon
              aria-hidden="true"
              className="size-5 text-success-foreground"
            />
          ) : (
            <ShieldXIcon
              aria-hidden="true"
              className="size-5 text-destructive"
            />
          )}
          <span className="font-mono text-sm font-medium">{item.key}</span>
          <Badge variant={item.available ? "default" : "destructive"}>
            {t(item.available ? "allowed" : "denied")}
          </Badge>
        </div>
        <KeyValue label={t("reason")} value={label(t, item.reason)} />
        {item.kind === "feature" ? (
          <>
            <KeyValue
              label={t("readDecision")}
              value={t(item.read_allowed ? "allowed" : "denied")}
            />
            <KeyValue
              label={t("readReason")}
              value={label(t, item.read_reason ?? "unknown")}
            />
          </>
        ) : (
          <>
            <KeyValue
              label={t("limit")}
              value={formatNumber(item.value, locale)}
            />
            <KeyValue
              label={t("used")}
              value={formatNumber(item.used, locale)}
            />
            <KeyValue
              label={t("reserved")}
              value={formatNumber(item.reserved, locale)}
            />
            <KeyValue
              label={t("period")}
              value={formatPeriod(item.period_start, item.period_end, locale)}
            />
          </>
        )}
      </div>

      <div className="space-y-4 rounded-lg border p-4">
        <h3 className="font-medium">{t("sourceTitle")}</h3>
        <KeyValue
          label={t("sourceKind")}
          value={label(t, evidence?.kind ?? "unknown")}
        />
        <KeyValue label={t("sourceRef")} value={evidence?.ref ?? "—"} />
        {evidence?.reason && (
          <KeyValue label={t("overrideReason")} value={evidence.reason} />
        )}
        {evidence?.expires_at && (
          <KeyValue
            label={t("expiresAt")}
            value={formatDate(evidence.expires_at, locale)}
          />
        )}
        {evidence?.expired_at && (
          <KeyValue
            label={t("expiredAt")}
            value={formatDate(evidence.expired_at, locale)}
          />
        )}
        {evidence?.fallback_source?.kind && (
          <KeyValue
            label={t("fallback")}
            value={`${label(t, evidence.fallback_source.kind)} · ${evidence.fallback_source.ref ?? "—"}`}
          />
        )}
      </div>
    </div>
  );
}

function SummaryCard({
  label: title,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle>{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function KeyValue({ label: title, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
      <span className="text-sm text-muted-foreground">{title}</span>
      <span className="break-all text-sm font-medium">{value}</span>
    </div>
  );
}

function asEvidence(value: unknown): Evidence | null {
  return typeof value === "object" && value !== null
    ? (value as Evidence)
    : null;
}

function label(t: Translator, value: string): string {
  const known = new Set([
    "active",
    "allowed",
    "blocked",
    "expired_override",
    "feature_disabled",
    "full",
    "override",
    "plan",
    "quota_available",
    "quota_missing",
    "read_only",
    "snapshot_expired",
    "snapshot_missing",
    "unknown",
    "unknown_feature",
    "unknown_quota",
  ]);
  return known.has(value) ? t(`labels.${value}`) : value;
}

function formatNumber(value: number | null, locale: string): string {
  return value === null ? "—" : new Intl.NumberFormat(locale).format(value);
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatPeriod(
  start: string | null,
  end: string | null,
  locale: string,
): string {
  if (!start) return "—";
  const formatter = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  return `${formatter.format(new Date(`${start}T00:00:00Z`))} – ${
    end ? formatter.format(new Date(`${end}T00:00:00Z`)) : "∞"
  }`;
}
