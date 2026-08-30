"use client";

import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { OctagonXIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import {
  listAutomationConnections,
  revokeAutomationGrant,
  type AutomationConnection,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Textarea } from "@saas-core/ui/components/textarea";

import { sitesErrorMessage } from "./problem";

type AutomationScope = {
  kind: "site" | "collection";
  id: string;
  name: string;
};

type RevokeValues = { reason: string };

function connectionScope(connection: AutomationConnection): AutomationScope {
  // DRF's DictField loses its closed value shape during OpenAPI generation.
  return connection.scope as AutomationScope;
}

function RevokeGrantDialog({
  connection,
  onRevoked,
}: {
  connection: AutomationConnection;
  onRevoked: (connections: AutomationConnection[]) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        reason: z
          .string()
          .trim()
          .min(1, t("connectionRevokeReasonRequired"))
          .max(500, t("connectionRevokeReasonTooLong")),
      }),
    [t],
  );
  const form = useForm<RevokeValues>({
    resolver: zodResolver(schema),
    defaultValues: { reason: "" },
    mode: "onChange",
  });

  const submit: SubmitHandler<RevokeValues> = async (values) => {
    setBusy(true);
    setProblem(undefined);
    try {
      const connections = await revokeAutomationGrant(
        connection.grant_id,
        values.reason.trim(),
      );
      onRevoked(connections);
      form.reset({ reason: "" });
      setOpen(false);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  };

  const reasonId = `connection-revoke-reason-${connection.grant_id}`;

  return (
    <Dialog
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setProblem(undefined);
          form.reset({ reason: "" });
        }
      }}
      open={open}
    >
      <DialogTrigger render={<Button type="button" variant="destructive" />}>
        <OctagonXIcon aria-hidden="true" />
        {t("connectionEmergencyRevoke")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("connectionRevokeTitle")}</DialogTitle>
          <DialogDescription>
            {t("connectionRevokeDescription")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            void form.handleSubmit(submit)(event);
          }}
        >
          <Field>
            <FieldLabel htmlFor={reasonId}>
              {t("connectionRevokeReason")}
            </FieldLabel>
            <Textarea
              aria-invalid={Boolean(form.formState.errors.reason)}
              autoFocus
              id={reasonId}
              maxLength={500}
              rows={4}
              {...form.register("reason")}
            />
            {form.formState.errors.reason && (
              <FieldError role="alert">
                {form.formState.errors.reason.message}
              </FieldError>
            )}
          </Field>
          {problem && (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          )}
          <DialogFooter>
            <Button
              disabled={busy || !form.formState.isValid}
              type="submit"
              variant="destructive"
            >
              <OctagonXIcon aria-hidden="true" />
              {busy ? t("connectionRevoking") : t("connectionRevokeSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AutomationConnectionsPanel() {
  const t = useTranslations("Sites");
  const locale = useLocale();
  const [connections, setConnections] = useState<AutomationConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    [locale],
  );
  const numberFormatter = useMemo(
    () => new Intl.NumberFormat(locale),
    [locale],
  );

  useEffect(() => {
    let mounted = true;
    void listAutomationConnections()
      .then((items) => {
        if (mounted) setConnections(items);
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
  }, [t]);

  const modeLabel = (mode: string) => {
    switch (mode) {
      case "suggest_only":
        return t("connectionModeSuggestOnly");
      case "draft_write":
        return t("connectionModeDraftWrite");
      case "publish_with_approval":
        return t("connectionModePublishWithApproval");
      case "autonomous":
        return t("connectionModeAutonomous");
      default:
        return t("connectionModeUnknown");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("connectionsTitle")}</CardTitle>
        <CardDescription>{t("connectionsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : loading ? (
          <p className="text-sm text-muted-foreground">
            {t("connectionsLoading")}
          </p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("connectionsEmpty")}
          </p>
        ) : (
          <ul className="space-y-4">
            {connections.map((connection) => {
              const scope = connectionScope(connection);
              const state = connection.revoked_at
                ? "revoked"
                : connection.active
                  ? "active"
                  : "expired";
              const stateLabel =
                state === "revoked"
                  ? t("connectionStateRevoked")
                  : state === "active"
                    ? t("connectionStateActive")
                    : t("connectionStateExpired");

              return (
                <li
                  className="space-y-4 rounded-lg border p-4"
                  key={connection.grant_id}
                >
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">
                        {t("connectionCredential")}
                      </p>
                      <code className="break-all text-sm">
                        {connection.credential_id}
                      </code>
                    </div>
                    <Badge
                      variant={
                        state === "revoked"
                          ? "destructive"
                          : state === "active"
                            ? "default"
                            : "outline"
                      }
                    >
                      {stateLabel}
                    </Badge>
                  </div>

                  <dl className="grid gap-3 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionMode")}
                      </dt>
                      <dd className="font-medium">
                        {modeLabel(connection.mode)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionScope")}
                      </dt>
                      {/* Separate words, not just separate boxes: a margin is
                          invisible to a screen reader, which read the label and
                          the name as one run-on word. */}
                      <dd className="flex flex-wrap items-baseline gap-2">
                        <span className="font-medium">
                          {scope.kind === "site"
                            ? t("connectionScopeSite")
                            : t("connectionScopeCollection")}
                        </span>{" "}
                        <span>{scope.name}</span>{" "}
                        <code className="break-all">{scope.id}</code>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionExpires")}
                      </dt>
                      <dd>
                        {connection.expires_at
                          ? dateFormatter.format(
                              new Date(connection.expires_at),
                            )
                          : t("connectionNoExpiry")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionLastActivity")}
                      </dt>
                      <dd>
                        {connection.last_activity_at
                          ? dateFormatter.format(
                              new Date(connection.last_activity_at),
                            )
                          : t("connectionNever")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionDailyLimit")}
                      </dt>
                      <dd>
                        {connection.max_changes_per_day === null
                          ? t("connectionUnlimited")
                          : t("connectionDailyLimitValue", {
                              count: numberFormatter.format(
                                connection.max_changes_per_day,
                              ),
                            })}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionPayloadLimit")}
                      </dt>
                      <dd>
                        {connection.max_payload_bytes === null
                          ? t("connectionUnlimited")
                          : t("connectionPayloadLimitValue", {
                              count: numberFormatter.format(
                                connection.max_payload_bytes,
                              ),
                            })}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("connectionWindow")}
                      </dt>
                      <dd>
                        {connection.window_start && connection.window_end
                          ? t("connectionWindowValue", {
                              start: connection.window_start,
                              end: connection.window_end,
                            })
                          : t("connectionAnyTime")}
                      </dd>
                    </div>
                    {connection.revoked_at && (
                      <div>
                        <dt className="text-muted-foreground">
                          {t("connectionRevokedAt")}
                        </dt>
                        <dd>
                          {dateFormatter.format(
                            new Date(connection.revoked_at),
                          )}
                        </dd>
                      </div>
                    )}
                  </dl>

                  {state === "active" && (
                    <div className="flex justify-end">
                      <RevokeGrantDialog
                        connection={connection}
                        onRevoked={setConnections}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
