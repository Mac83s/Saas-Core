"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  ApiProblemError,
  authorizeSeoGsc,
  createSeoGscGrant,
  disconnectSeoGsc,
  getSeoGscProperties,
  getSeoGscConnection,
  listSeoGscSyncs,
  listSeoGscGrants,
  listSites,
  prepareSeoGsc,
  readSeoGscGrant,
  readSeoGscMetrics,
  revokeSeoGsc,
  syncSeoGsc,
  retrySeoGscGrant,
  type GscGrant,
  type GscGrantList,
  type GscGrantInput,
  type GscMetrics,
  type GscProperties,
  type GscSyncInput,
  type GscSyncHistory,
  type SiteSummary,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Combobox,
  ComboboxInput,
  ComboboxContent,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
} from "@saas-core/ui/components/combobox";
import { Link } from "#i18n/navigation";

export function SeoGscPanel() {
  const t = useTranslations("SeoGsc");
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [siteId, setSiteId] = useState("");
  const [problem, setProblem] = useState(false);
  useEffect(() => {
    let active = true;
    void listSites()
      .then((value) => {
        if (active) setSites(value.items);
      })
      .catch(() => {
        if (active) setProblem(true);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">{t("title")}</h1>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          {t("description")}
        </p>
        <Link href="/panel/seo" className="mt-3 inline-block underline">
          {t("audits")}
        </Link>
      </header>
      {problem ? <p role="alert">{t("unavailable")}</p> : null}
      <Field>
        <FieldLabel htmlFor="gsc-site">{t("site")}</FieldLabel>
        {sites.length <= 20 ? (
          <NativeSelect
            id="gsc-site"
            value={siteId}
            onChange={(event) => setSiteId(event.target.value)}
          >
            <option value="">{t("chooseSite")}</option>
            {sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <Combobox
            items={sites}
            value={sites.find((site) => site.id === siteId) ?? null}
            onValueChange={(site) => setSiteId(site?.id ?? "")}
            itemToStringLabel={(site) => site.name}
          >
            <ComboboxInput id="gsc-site" placeholder={t("chooseSite")} />
            <ComboboxContent>
              <ComboboxEmpty>{t("empty")}</ComboboxEmpty>
              <ComboboxList>
                {(site: SiteSummary) => (
                  <ComboboxItem key={site.id} value={site}>
                    {site.name}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
        )}
      </Field>
      {siteId ? <SiteGsc key={siteId} siteId={siteId} /> : null}
    </div>
  );
}

function SiteGsc({ siteId }: { siteId: string }) {
  const t = useTranslations("SeoGsc");
  const locale = useLocale();
  const [properties, setProperties] = useState<GscProperties>();
  const [history, setHistory] = useState<GscGrantList>({
    items: [],
    next_cursor: null,
  });
  const [grant, setGrant] = useState<GscGrant>();
  const [metrics, setMetrics] = useState<GscMetrics>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [syncId, setSyncId] = useState<string>();
  const [syncSaved, setSyncSaved] = useState(false);
  const [syncHistory, setSyncHistory] = useState<GscSyncHistory>({ items: [] });
  const active = useRef(true);
  const lock = useRef(false);
  const grantIntent = useRef<GscGrantInput | undefined>(undefined);
  const syncIntent = useRef<GscSyncInput | undefined>(undefined);
  const grantSchema = useMemo(
    () => z.object({ propertyId: z.string().uuid(t("chooseProperty")) }),
    [t],
  );
  const grantForm = useForm<z.infer<typeof grantSchema>>({
    resolver: zodResolver(grantSchema),
    defaultValues: { propertyId: "" },
  });
  const syncSchema = useMemo(
    () =>
      z.object({ startDate: z.string().min(1), endDate: z.string().min(1) }),
    [],
  );
  const [initialDates] = useState(() => ({
    startDate: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
    endDate: new Date(Date.now() - 86400000).toISOString().slice(0, 10),
  }));
  const dateForm = useForm<z.infer<typeof syncSchema>>({
    resolver: zodResolver(syncSchema),
    defaultValues: initialDates,
  });
  const propertyId = useWatch({
    control: grantForm.control,
    name: "propertyId",
  });
  const explain = useCallback(
    (error: unknown) => {
      if (error instanceof ApiProblemError && error.problem.status === 403)
        return t("forbidden");
      if (error instanceof ApiProblemError && error.problem.status === 409)
        return t("conflict");
      return t("unavailable");
    },
    [t],
  );
  const refresh = useCallback(
    () =>
      Promise.allSettled([
        getSeoGscProperties(siteId).catch(async () => ({
          ...(await getSeoGscConnection(siteId)),
          properties: [],
        })),
        listSeoGscGrants(siteId),
      ]).then(([props, rows]) => {
        if (!active.current) return;
        setMetrics(undefined);
        setProperties(props.status === "fulfilled" ? props.value : undefined);
        setHistory(
          rows.status === "fulfilled"
            ? rows.value
            : { items: [], next_cursor: null },
        );
        if (rows.status === "rejected") {
          setGrant(undefined);
          setMetrics(undefined);
          setProblem(explain(rows.reason));
        }
      }),
    [siteId, explain],
  );
  useEffect(() => {
    active.current = true;
    void refresh();
    return () => {
      active.current = false;
    };
  }, [refresh]);
  const run = async (operation: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setProblem(undefined);
    try {
      await operation();
    } catch (error) {
      if (active.current) {
        setMetrics(undefined);
        setProblem(explain(error));
      }
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  };
  const selectGrant = async (id: string) => {
    setMetrics(undefined);
    setGrant(undefined);
    setSyncId(undefined);
    syncIntent.current = undefined;
    const value = await readSeoGscGrant(id);
    if (active.current) {
      setGrant(value);
      setSyncId(value.latest_sync?.id ?? undefined);
      setSyncHistory(await listSeoGscSyncs(id));
      setSyncSaved(false);
    }
  };
  const submitGrant = async (values: z.infer<typeof grantSchema>) => {
    await run(async () => {
      grantIntent.current ??= {
        site_id: siteId,
        property_id: values.propertyId,
        expires_at: new Date(Date.now() + 30 * 86400000).toISOString(),
        idempotency_key: crypto.randomUUID(),
      };
      setUncertain(true);
      const value = await createSeoGscGrant(grantIntent.current);
      grantIntent.current = undefined;
      if (active.current) {
        setUncertain(false);
        setGrant(value);
        await refresh();
      }
    });
  };
  const submitSync = async (values: z.infer<typeof syncSchema>) => {
    if (!grant) return;
    await run(async () => {
      setSyncSaved(true);
      syncIntent.current ??= {
        client_reference: crypto.randomUUID(),
        start_date: values.startDate,
        end_date: values.endDate,
      };
      const value = await syncSeoGsc(grant.id, syncIntent.current);
      if (active.current) {
        setSyncId(value.id ?? undefined);
        setGrant(await readSeoGscGrant(grant.id));
      }
      // Keep the receipt for polling/retry; a new range needs an explicit new request.
    });
  };
  const loadMetrics = async (page = 1) => {
    if (!grant || !syncId) return;
    const value = await readSeoGscMetrics(grant.id, syncId, page);
    if (active.current) setMetrics(value);
  };
  return (
    <div className="space-y-6" aria-busy={busy}>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {uncertain ? <p role="status">{t("uncertain")}</p> : null}
      <Card>
        <CardHeader>
          <CardTitle>{t("connection")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p>{properties?.connected ? t("connected") : t("notConnected")}</p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void run(refresh)}
            >
              {t("refresh")}
            </Button>
            {!properties ? (
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const value = await prepareSeoGsc({ site_id: siteId });
                    if (active.current) setProperties(value);
                  })
                }
              >
                {t("prepare")}
              </Button>
            ) : null}
            {properties && !properties.connected ? (
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const value = await authorizeSeoGsc({
                      site_id: siteId,
                      connection_id: null,
                      locale: locale === "en" ? "en" : "pl",
                    });
                    if (active.current)
                      window.location.assign(value.authorization_url);
                  })
                }
              >
                {t("connect")}
              </Button>
            ) : null}
          </div>
          {properties ? (
            <div className="space-y-3 border-t pt-4">
              <p className="text-sm text-muted-foreground">
                {t("disconnectScope")}
              </p>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={confirm}
                  onChange={(event) => setConfirm(event.target.checked)}
                />
                {t("confirmDisconnect")}
              </label>
              <Button
                variant="outline"
                disabled={busy || !confirm}
                onClick={() =>
                  void run(async () => {
                    const value = await disconnectSeoGsc({
                      site_id: siteId,
                      connection_id: properties.connection_id,
                      confirm_workspace_disconnect: true,
                    });
                    if (active.current) {
                      setMetrics(undefined);
                      setGrant(undefined);
                      setConfirm(false);
                      if (!value.disconnected) setProblem(t("disconnectAgain"));
                      await refresh();
                    }
                  })
                }
              >
                {t("disconnect")}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
      {properties?.connected ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("grantTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) =>
                void grantForm.handleSubmit(submitGrant)(event)
              }
            >
              <p>{t("grantScope")}</p>
              <Field>
                <FieldLabel htmlFor="gsc-property">{t("property")}</FieldLabel>
                {properties.properties.length <= 20 ? (
                  <NativeSelect
                    id="gsc-property"
                    {...grantForm.register("propertyId")}
                    disabled={busy || uncertain}
                  >
                    <option value="">{t("chooseProperty")}</option>
                    {properties.properties.map((property) => (
                      <option key={property.id} value={property.id}>
                        {property.site_url}
                      </option>
                    ))}
                  </NativeSelect>
                ) : (
                  <Combobox
                    items={properties.properties}
                    value={
                      properties.properties.find(
                        (property) => property.id === propertyId,
                      ) ?? null
                    }
                    onValueChange={(property) =>
                      grantForm.setValue("propertyId", property?.id ?? "")
                    }
                    itemToStringLabel={(property) => property.site_url}
                    disabled={busy || uncertain}
                  >
                    <ComboboxInput id="gsc-property" />
                    <ComboboxContent>
                      <ComboboxEmpty>{t("empty")}</ComboboxEmpty>
                      <ComboboxList>
                        {(property: GscProperties["properties"][number]) => (
                          <ComboboxItem key={property.id} value={property}>
                            {property.site_url}
                          </ComboboxItem>
                        )}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                )}
                <FieldError>
                  {grantForm.formState.errors.propertyId?.message}
                </FieldError>
              </Field>
              <Button type="submit" disabled={busy}>
                {uncertain ? t("retry") : t("grant")}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>{t("history")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!history.items.length ? (
            <p>{t("empty")}</p>
          ) : (
            <ul className="space-y-2">
              {history.items.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center gap-3">
                  <span>
                    {t("expires", {
                      date: new Date(row.expires_at).toLocaleDateString(locale),
                    })}
                  </span>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        if (!row.outcome_known) await retrySeoGscGrant(row.id);
                        await selectGrant(row.id);
                        await refresh();
                      })
                    }
                  >
                    {row.outcome_known ? t("open") : t("retry")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {history.next_cursor ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const rows = await listSeoGscGrants(
                    siteId,
                    history.next_cursor ?? undefined,
                  );
                  if (active.current)
                    setHistory((current) => ({
                      items: [...current.items, ...rows.items],
                      next_cursor: rows.next_cursor,
                    }));
                })
              }
            >
              {t("more")}
            </Button>
          ) : null}
        </CardContent>
      </Card>
      {grant ? (
        <Card>
          <CardHeader>
            <CardTitle>{grant.site_url ?? t("grantTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p>{grant.connected ? t("grantActive") : t("grantInactive")}</p>
            {grant.connected && syncHistory.items.length ? (
              <ul className="space-y-2">
                {syncHistory.items.map((row) => (
                  <li
                    key={row.client_reference}
                    className="flex flex-wrap items-center gap-3"
                  >
                    <span>
                      {row.start_date} – {row.end_date}
                    </span>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const result = await syncSeoGsc(grant.id, {
                            client_reference: row.client_reference,
                            start_date: row.start_date,
                            end_date: row.end_date,
                          });
                          if (active.current) {
                            setSyncId(result.id ?? undefined);
                            setGrant(await readSeoGscGrant(grant.id));
                            setMetrics(undefined);
                          }
                        })
                      }
                    >
                      {t("retry")}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const value = await revokeSeoGsc(grant.id, {});
                  if (active.current) {
                    setGrant(value);
                    setMetrics(undefined);
                    setSyncId(undefined);
                  }
                })
              }
            >
              {t("revoke")}
            </Button>
            {grant.connected ? (
              <form
                className="flex flex-wrap items-end gap-4"
                onSubmit={(event) =>
                  void dateForm.handleSubmit(submitSync)(event)
                }
              >
                <Field>
                  <FieldLabel htmlFor="gsc-from">{t("from")}</FieldLabel>
                  <Input
                    id="gsc-from"
                    type="date"
                    {...dateForm.register("startDate")}
                    disabled={busy || syncSaved}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="gsc-to">{t("to")}</FieldLabel>
                  <Input
                    id="gsc-to"
                    type="date"
                    {...dateForm.register("endDate")}
                    disabled={busy || syncSaved}
                  />
                </Field>
                <Button type="submit" disabled={busy}>
                  {t("sync")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    syncIntent.current = undefined;
                    setSyncSaved(false);
                    setSyncId(undefined);
                    setMetrics(undefined);
                  }}
                >
                  {t("newSync")}
                </Button>
              </form>
            ) : null}
            {grant.latest_sync ? (
              <p role="status">
                {t("syncStatus", { status: grant.latest_sync.status })}
                {grant.latest_sync.is_truncated ? ` ${t("truncated")}` : ""}
              </p>
            ) : null}
            {syncId && grant.connected ? (
              <Button
                disabled={busy}
                variant="outline"
                onClick={() => void run(() => loadMetrics())}
              >
                {t("metrics")}
              </Button>
            ) : null}
            {metrics ? (
              <div className="overflow-x-auto">
                <p>{t("rowCount", { count: metrics.count })}</p>
                <table className="w-full text-sm">
                  <caption className="sr-only">{t("metrics")}</caption>
                  <thead>
                    <tr>
                      {[
                        "date",
                        "query",
                        "page",
                        "clicks",
                        "impressions",
                        "position",
                      ].map((key) => (
                        <th key={key} scope="col" className="p-2 text-left">
                          {t(key)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.results.map((row, index) => (
                      <tr key={index} className="border-t">
                        <td className="p-2">{row.date}</td>
                        <td className="p-2">{row.query}</td>
                        <td className="p-2 break-all">{row.page}</td>
                        <td className="p-2">{row.clicks}</td>
                        <td className="p-2">{row.impressions}</td>
                        <td className="p-2">{row.position}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {metrics.next_page ? (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(() => loadMetrics(metrics.next_page ?? 1))
                    }
                  >
                    {t("more")}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
