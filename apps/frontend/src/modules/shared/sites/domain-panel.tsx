"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2Icon, CopyIcon, Globe2Icon, PlusIcon } from "lucide-react";
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
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { sitesErrorMessage } from "./problem";

type DomainValues = { hostname: string };

export function DomainPanel({ siteId }: { siteId: string }) {
  const t = useTranslations("Sites");
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
    setProblem(undefined);
    try {
      await mutateSiteDomain(domain.id, { action: value }, crypto.randomUUID());
      await load();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
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

        {domains.length === 0 && !loading ? (
          <p className="text-sm text-muted-foreground">{t("noDomains")}</p>
        ) : (
          <div className="space-y-3">
            {domains.map((domain) => (
              <DomainRow
                domain={domain}
                key={domain.id}
                loading={loading}
                onAction={(value) => void action(domain, value)}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DomainRow({
  domain,
  loading,
  onAction,
}: {
  domain: SiteDomain;
  loading: boolean;
  onAction: (action: DomainActionInput["action"]) => void;
}) {
  const t = useTranslations("Sites");
  const custom = domain.kind === "custom";
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Globe2Icon aria-hidden="true" className="size-4" />
        <strong className="break-all">{domain.hostname}</strong>
        <Badge variant={domain.status === "verified" ? "default" : "secondary"}>
          {t(`domainStatus_${domain.status}`)}
        </Badge>
        <Badge variant="outline">
          TLS: {t(`tlsStatus_${domain.tls_status}`)}
        </Badge>
        {domain.is_canonical && (
          <Badge variant="outline">
            <CheckCircle2Icon aria-hidden="true" /> {t("canonical")}
          </Badge>
        )}
      </div>

      {custom && domain.status !== "released" && (
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

      <div className="flex flex-wrap gap-2">
        {custom && !["disabled", "released"].includes(domain.status) && (
          <Button
            disabled={loading}
            onClick={() => onAction("verify")}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("verifyDomain")}
          </Button>
        )}
        {domain.status === "verified" && !domain.is_canonical && (
          <Button
            disabled={loading}
            onClick={() => onAction("set_canonical")}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("setCanonical")}
          </Button>
        )}
        {domain.status === "disabled" ? (
          <Button
            disabled={loading}
            onClick={() => onAction("enable")}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("enableDomain")}
          </Button>
        ) : domain.status !== "released" ? (
          <Button
            disabled={loading}
            onClick={() => onAction("disable")}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("disableDomain")}
          </Button>
        ) : null}
      </div>
    </article>
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
