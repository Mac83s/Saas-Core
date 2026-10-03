"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  LaptopIcon,
  LogOutIcon,
  RefreshCwIcon,
  SmartphoneIcon,
} from "lucide-react";

import {
  ApiProblemError,
  listSessions,
  logoutAccount,
  revokeSession,
  type SessionSummary,
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

import { useRouter } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { identityErrorMessage } from "./problem";

export function LogoutButton() {
  const t = useTranslations("Panel");
  const router = useRouter();
  const [pending, setPending] = useState(false);
  return (
    <Button
      disabled={pending}
      onClick={async () => {
        setPending(true);
        try {
          await logoutAccount();
        } finally {
          router.replace("/login");
          router.refresh();
        }
      }}
      variant="outline"
    >
      <LogOutIcon aria-hidden="true" />
      {pending ? t("loggingOut") : t("logout")}
    </Button>
  );
}

export function SessionManager() {
  const t = useTranslations("Sessions");
  const identity = useTranslations("Identity");
  const labels = useDataTableLabels();
  const locale = useLocale();
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [problem, setProblem] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      setSessions(await listSessions());
    } catch (error) {
      if (error instanceof ApiProblemError && error.problem.status === 403) {
        router.replace("/login");
        return;
      }
      setProblem(identityErrorMessage(error, problemMessages(identity)));
    } finally {
      setLoading(false);
    }
  }, [identity, router]);

  useEffect(() => {
    let active = true;
    void listSessions()
      .then((items) => {
        if (active) setSessions(items);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiProblemError && error.problem.status === 403) {
          router.replace("/login");
          return;
        }
        setProblem(identityErrorMessage(error, problemMessages(identity)));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [identity, router]);

  async function revoke(session: SessionSummary) {
    // The menu stays usable while a revoke runs; one at a time.
    if (revoking) return;
    setRevoking(session.id);
    setProblem(undefined);
    try {
      await revokeSession(session.id);
      if (session.current) {
        router.replace("/login");
        router.refresh();
        return;
      }
      await load();
    } catch (error) {
      setProblem(identityErrorMessage(error, problemMessages(identity)));
    } finally {
      setRevoking(undefined);
    }
  }

  const columns: ColumnDef<SessionSummary, unknown>[] = [
    {
      id: "device",
      accessorKey: "device_label",
      header: t("colDevice"),
      meta: { primary: true },
      cell: ({ row: { original: session } }) => (
        <div className="flex items-center gap-3">
          {/mobile|android|iphone/i.test(session.device_label) ? (
            <SmartphoneIcon
              aria-hidden="true"
              className="size-5 shrink-0 text-muted-foreground"
            />
          ) : (
            <LaptopIcon
              aria-hidden="true"
              className="size-5 shrink-0 text-muted-foreground"
            />
          )}
          <p className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium">
            <span className="wrap-anywhere">{session.device_label}</span>
            {session.current ? (
              <Badge variant="secondary">{t("current")}</Badge>
            ) : null}
            {revoking === session.id ? (
              <span className="font-normal text-muted-foreground">
                {t("ending")}
              </span>
            ) : null}
          </p>
        </div>
      ),
    },
    {
      id: "lastActive",
      accessorKey: "last_seen_at",
      header: t("lastActive"),
      cell: ({ row: { original: session } }) =>
        formatDate(session.last_seen_at, locale),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: session } }) => (
        <RowActions
          items={[
            {
              label: t("logout"),
              icon: <LogOutIcon aria-hidden="true" />,
              destructive: true,
              onSelect: () => void revoke(session),
            },
          ]}
          label={t("actionsFor", { device: session.device_label })}
        />
      ),
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        <Button
          aria-label={t("refresh")}
          onClick={() => void load()}
          size="icon"
          variant="outline"
        >
          <RefreshCwIcon
            aria-hidden="true"
            className={loading ? "animate-spin" : ""}
          />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3" aria-live="polite">
        {problem && (
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            role="alert"
          >
            {problem}
          </div>
        )}
        <DataTable
          caption={t("title")}
          columns={columns}
          data={sessions}
          getRowId={(session) => session.id}
          labels={{ ...labels, empty: t("empty") }}
          loading={loading}
        />
      </CardContent>
    </Card>
  );
}

type IdentityTranslator = ReturnType<typeof useTranslations<"Identity">>;

function problemMessages(t: IdentityTranslator) {
  return {
    invalidCredentials: t("invalidCredentials"),
    invalidMfaCode: t("invalidMfaCode"),
    mfaSetupRequired: t("mfaSetupRequired"),
    mfaLocked: t("mfaLocked"),
    apiUnavailable: t("apiUnavailable"),
  };
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
