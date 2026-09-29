"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  CheckCircle2Icon,
  CopyIcon,
  PlusIcon,
  PowerIcon,
  RefreshCwIcon,
  StarIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import {
  createSiteDomain,
  listSiteDomains,
  mutateSiteDomain,
  type DomainActionInput,
  type SiteDomain,
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
  DataTable,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { useDataTableLabels } from "#lib/data-table-labels";
import { sitesErrorMessage } from "./problem";

type DomainValues = { hostname: string };

export function DomainPanel({ siteId }: { siteId: string }) {
  const t = useTranslations("Sites");
  const labels = useDataTableLabels();
  const [domains, setDomains] = useState<SiteDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        hostname: z
          .string()
          .min(3, t("domainInvalid"))
          .max(253, t("domainInvalid")),
      }),
    [t],
  );
  const form = useForm<DomainValues>({
    resolver: zodResolver(schema),
    defaultValues: { hostname: "" },
  });

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      setDomains((await listSiteDomains(siteId)).items);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }, [siteId, t]);

  useEffect(() => {
    let mounted = true;
    void listSiteDomains(siteId)
      .then((result) => {
        if (mounted) setDomains(result.items);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [siteId, t]);

  const submit: SubmitHandler<DomainValues> = async (values) => {
    setProblem(undefined);
    try {
      await createSiteDomain(siteId, values, crypto.randomUUID());
      form.reset();
      await load();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  };

  async function action(
    domain: SiteDomain,
    value: DomainActionInput["action"],
  ) {
    // One change at a time: the list reloads after each.
    if (loading) return;
    setProblem(undefined);
    try {
      await mutateSiteDomain(domain.id, { action: value }, crypto.randomUUID());
      await load();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  }

  const columns: ColumnDef<SiteDomain, unknown>[] = [
    {
      id: "hostname",
      accessorKey: "hostname",
      header: t("lists.domainColumn"),
      meta: { primary: true },
      cell: ({ row: { original: domain } }) => (
        <div className="space-y-3">
          <p className="flex flex-wrap items-center gap-2">
            <strong className="break-all">{domain.hostname}</strong>
            {domain.is_canonical && (
              <Badge variant="outline">
                <CheckCircle2Icon aria-hidden="true" /> {t("canonical")}
              </Badge>
            )}
          </p>
          {/* What to set at the registrar stays with its domain until the
              domain is released. */}
          {domain.kind === "custom" && domain.status !== "released" && (
            <div className="space-y-2 rounded-md bg-muted/50 p-3 text-sm">
              <p>{t("dnsInstruction")}</p>
              <DnsValue
                label="TXT"
                value={`${domain.verification_name} = ${domain.verification_token}`}
              />
              <DnsValue
                label="CNAME"
                value={`${domain.hostname} = ${domain.dns_cname_target}`}
              />
              {domain.dns_error_code && (
                <p className="text-destructive">
                  {t("dnsError", { code: domain.dns_error_code })}
                </p>
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      id: "status",
      accessorFn: (domain) => t(`domainStatus_${domain.status}`),
      header: t("lists.state"),
      cell: ({ row: { original: domain } }) => (
        <div className="flex flex-wrap gap-2 max-md:justify-end">
          <Badge
            variant={domain.status === "verified" ? "default" : "secondary"}
          >
            {t(`domainStatus_${domain.status}`)}
          </Badge>
          <Badge variant="outline">
            TLS: {t(`tlsStatus_${domain.tls_status}`)}
          </Badge>
        </div>
      ),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      cell: ({ row: { original: domain } }) => (
        <RowActions
          items={domainActions(domain)}
          label={t("lists.domainActionsFor", { hostname: domain.hostname })}
        />
      ),
    },
  ];

  function domainActions(domain: SiteDomain): RowAction[] {
    const custom = domain.kind === "custom";
    const items: RowAction[] = [];
    if (custom && !["disabled", "released"].includes(domain.status))
      items.push({
        label: t("verifyDomain"),
        icon: <RefreshCwIcon aria-hidden="true" />,
        inline: true,
        onSelect: () => void action(domain, "verify"),
      });
    if (domain.status === "verified" && !domain.is_canonical)
      items.push({
        label: t("setCanonical"),
        icon: <StarIcon aria-hidden="true" />,
        inline: true,
        onSelect: () => void action(domain, "set_canonical"),
      });
    if (domain.status === "disabled")
      items.push({
        label: t("enableDomain"),
        icon: <PowerIcon aria-hidden="true" />,
        inline: true,
        onSelect: () => void action(domain, "enable"),
      });
    else if (domain.status !== "released")
      items.push({
        label: t("disableDomain"),
        destructive: true,
        onSelect: () => void action(domain, "disable"),
      });
    return items;
  }

  return (
    <Card aria-labelledby="site-domains-title">
      <CardHeader>
        <CardTitle id="site-domains-title">{t("domains")}</CardTitle>
        <CardDescription>{t("domainsDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {problem && (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={form.handleSubmit(submit)}
        >
          <Field
            className="flex-1"
            data-invalid={Boolean(form.formState.errors.hostname)}
          >
            <FieldLabel htmlFor="custom-domain-hostname">
              {t("customDomain")}
            </FieldLabel>
            <Input
              aria-invalid={Boolean(form.formState.errors.hostname)}
              autoCapitalize="none"
              autoComplete="url"
              id="custom-domain-hostname"
              placeholder="www.example.com"
              spellCheck={false}
              {...form.register("hostname")}
            />
            <FieldError>{form.formState.errors.hostname?.message}</FieldError>
          </Field>
          <Button disabled={form.formState.isSubmitting} type="submit">
            <PlusIcon aria-hidden="true" />
            {t("addDomain")}
          </Button>
        </form>

        <DataTable
          caption={t("lists.domainsCaption")}
          columns={columns}
          data={domains}
          getRowId={(domain) => domain.id}
          labels={{ ...labels, empty: t("noDomains") }}
          loading={loading}
        />
      </CardContent>
    </Card>
  );
}

function DnsValue({ label, value }: { label: string; value: string }) {
  const t = useTranslations("Sites");
  return (
    <div className="flex items-start justify-between gap-2 rounded border bg-background p-2">
      <code className="break-all text-xs">
        {label} {value}
      </code>
      <Button
        aria-label={t("copyDnsValue", { label })}
        onClick={() => void navigator.clipboard.writeText(value)}
        size="icon-sm"
        type="button"
        variant="ghost"
      >
        <CopyIcon aria-hidden="true" />
      </Button>
    </div>
  );
}
