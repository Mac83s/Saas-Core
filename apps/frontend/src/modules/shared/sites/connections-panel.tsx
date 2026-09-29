"use client";

import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { InfoIcon, OctagonXIcon } from "lucide-react";
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
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Textarea } from "@saas-core/ui/components/textarea";

import { useDataTableLabels } from "#lib/data-table-labels";
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
  finalFocus,
  onClose,
  onRevoked,
}: {
  connection: AutomationConnection;
  /** The row's button the dialog was opened from. */
  finalFocus: HTMLElement | null;
  onClose: () => void;
  onRevoked: (connections: AutomationConnection[]) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
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
  // Mounted per opening, so every attempt starts with an empty reason.
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
        if (!next) onClose();
      }}
      open
    >
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
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
            {/* The dialog focuses its first field itself; `autoFocus` can
                lose to the row menu handing focus back to its button as it
                closes. */}
            <Textarea
              aria-invalid={Boolean(form.formState.errors.reason)}
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
  const common = useTranslations("Common");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [connections, setConnections] = useState<AutomationConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [details, setDetails] = useState<AutomationConnection>();
  const [revoking, setRevoking] = useState<AutomationConnection>();
  // The row's button gets focus back when a dialog closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
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
  const stateOf = (connection: AutomationConnection) =>
    connection.revoked_at
      ? "revoked"
      : connection.active
        ? "active"
        : "expired";
  const stateLabel = (connection: AutomationConnection) => {
    const state = stateOf(connection);
    return state === "revoked"
      ? t("connectionStateRevoked")
      : state === "active"
        ? t("connectionStateActive")
        : t("connectionStateExpired");
  };
  const scopeKind = (scope: AutomationScope) =>
    scope.kind === "site"
      ? t("connectionScopeSite")
      : t("connectionScopeCollection");
  const expires = (connection: AutomationConnection) =>
    connection.expires_at
      ? dateFormatter.format(new Date(connection.expires_at))
      : t("connectionNoExpiry");
  const lastActivity = (connection: AutomationConnection) =>
    connection.last_activity_at
      ? dateFormatter.format(new Date(connection.last_activity_at))
      : t("connectionNever");

  const columns: ColumnDef<AutomationConnection, unknown>[] = [
    {
      id: "credential",
      accessorKey: "credential_id",
      header: t("connectionCredential"),
      meta: { primary: true },
      cell: ({ row: { original: connection } }) => (
        <code className="text-sm break-all">{connection.credential_id}</code>
      ),
    },
    {
      id: "state",
      accessorFn: stateLabel,
      header: t("lists.state"),
      cell: ({ row: { original: connection } }) => {
        const state = stateOf(connection);
        return (
          <Badge
            variant={
              state === "revoked"
                ? "destructive"
                : state === "active"
                  ? "default"
                  : "outline"
            }
          >
            {stateLabel(connection)}
          </Badge>
        );
      },
    },
    {
      id: "mode",
      accessorFn: (connection) => modeLabel(connection.mode),
      header: t("connectionMode"),
    },
    {
      id: "scope",
      accessorFn: (connection) => connectionScope(connection).name,
      header: t("connectionScope"),
      cell: ({ row: { original: connection } }) => {
        const scope = connectionScope(connection);
        // Separate words, not just separate boxes: a margin is invisible to
        // a screen reader, which read the kind and the name as one word.
        return (
          <span className="wrap-anywhere">
            <span className="font-medium">{scopeKind(scope)}</span>{" "}
            <span>{scope.name}</span>
          </span>
        );
      },
    },
    {
      id: "expires",
      accessorKey: "expires_at",
      header: t("connectionExpires"),
      cell: ({ row: { original: connection } }) => expires(connection),
    },
    {
      id: "lastActivity",
      accessorKey: "last_activity_at",
      header: t("connectionLastActivity"),
      cell: ({ row: { original: connection } }) => lastActivity(connection),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      cell: ({ row: { original: connection } }) => (
        <RowActions
          items={[
            {
              label: t("lists.connectionDetails"),
              icon: <InfoIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => {
                setReturnTo(trigger);
                setDetails(connection);
              },
            },
            // Offered only on a live grant: on a revoked or expired one it
            // would suggest there is something left to stop.
            ...(stateOf(connection) === "active"
              ? [
                  {
                    label: t("connectionEmergencyRevoke"),
                    icon: <OctagonXIcon aria-hidden="true" />,
                    destructive: true,
                    onSelect: (trigger: HTMLElement | null) => {
                      setReturnTo(trigger);
                      setRevoking(connection);
                    },
                  },
                ]
              : []),
          ]}
          label={t("lists.connectionActionsFor", {
            credential: connection.credential_id,
          })}
        />
      ),
    },
  ];

  const detailScope = details ? connectionScope(details) : undefined;

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
        ) : (
          <DataTable
            caption={t("lists.connectionsCaption")}
            columns={columns}
            data={connections}
            getRowId={(connection) => connection.grant_id}
            labels={{
              ...labels,
              empty: t("connectionsEmpty"),
              loading: t("connectionsLoading"),
            }}
            loading={loading}
          />
        )}
      </CardContent>
      {details && detailScope ? (
        <Dialog
          onOpenChange={(next) => {
            if (!next) setDetails(undefined);
          }}
          open
        >
          <DialogContent
            closeLabel={common("close")}
            finalFocus={() => returnTo ?? true}
          >
            <DialogHeader>
              <DialogTitle>{t("lists.connectionDetails")}</DialogTitle>
              <DialogDescription className="break-all">
                {t("connectionCredential")}: {details.credential_id}
              </DialogDescription>
            </DialogHeader>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">{t("lists.state")}</dt>
                <dd className="font-medium">{stateLabel(details)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("connectionMode")}</dt>
                <dd className="font-medium">{modeLabel(details.mode)}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">
                  {t("connectionScope")}
                </dt>
                <dd className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium">{scopeKind(detailScope)}</span>{" "}
                  <span>{detailScope.name}</span>{" "}
                  <code className="break-all">{detailScope.id}</code>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("connectionExpires")}
                </dt>
                <dd>{expires(details)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("connectionLastActivity")}
                </dt>
                <dd>{lastActivity(details)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("connectionDailyLimit")}
                </dt>
                <dd>
                  {details.max_changes_per_day === null
                    ? t("connectionUnlimited")
                    : t("connectionDailyLimitValue", {
                        count: numberFormatter.format(
                          details.max_changes_per_day,
                        ),
                      })}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("connectionPayloadLimit")}
                </dt>
                <dd>
                  {details.max_payload_bytes === null
                    ? t("connectionUnlimited")
                    : t("connectionPayloadLimitValue", {
                        count: numberFormatter.format(
                          details.max_payload_bytes,
                        ),
                      })}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("connectionWindow")}
                </dt>
                <dd>
                  {details.window_start && details.window_end
                    ? t("connectionWindowValue", {
                        start: details.window_start,
                        end: details.window_end,
                      })
                    : t("connectionAnyTime")}
                </dd>
              </div>
              {details.revoked_at && (
                <div>
                  <dt className="text-muted-foreground">
                    {t("connectionRevokedAt")}
                  </dt>
                  <dd>{dateFormatter.format(new Date(details.revoked_at))}</dd>
                </div>
              )}
            </dl>
          </DialogContent>
        </Dialog>
      ) : null}
      {revoking ? (
        <RevokeGrantDialog
          connection={revoking}
          finalFocus={returnTo}
          onClose={() => setRevoking(undefined)}
          onRevoked={(next) => {
            setConnections(next);
            setRevoking(undefined);
          }}
        />
      ) : null}
    </Card>
  );
}
