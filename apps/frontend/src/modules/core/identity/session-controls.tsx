"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  LaptopIcon,
  LogOutIcon,
  RefreshCwIcon,
  SmartphoneIcon,
  TabletIcon,
  TerminalIcon,
} from "lucide-react";

import {
  ApiProblemError,
  listSessions,
  logoutAccount,
  revokeOtherSessions,
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
import { describeDevice, type DeviceKind } from "./device";
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

type DeviceRow = {
  id: string;
  name: string;
  kind: DeviceKind;
  sessions: SessionSummary[];
  current: boolean;
  lastSeen: string;
};

const SHOWN = 5;

const DEVICE_ICONS = {
  desktop: LaptopIcon,
  phone: SmartphoneIcon,
  tablet: TabletIcon,
  script: TerminalIcon,
} as const;

/**
 * „Aktywne urządzenia” (UX-054): a name people read, one row per device
 * however many sessions it holds, the five most recent first, and a way to
 * sign out everywhere else at once.
 */
export function SessionManager() {
  const t = useTranslations("Sessions");
  const identity = useTranslations("Identity");
  const labels = useDataTableLabels();
  const locale = useLocale();
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [problem, setProblem] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string>();
  const [endingOthers, setEndingOthers] = useState(false);
  const [showAll, setShowAll] = useState(false);

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

  const deviceName = (label: string) => {
    const device = describeDevice(label);
    if (device.kind === "script") return t("script");
    if (device.browser)
      return [
        device.automated
          ? t("automated", { browser: device.browser })
          : device.browser,
        device.os,
      ]
        .filter(Boolean)
        .join(" · ");
    // A browser header we cannot read says its system at most; a plain label
    // someone gave the session is already a name.
    if (label.includes("/")) return device.os || t("unknownDevice");
    return label.trim() || t("unknownDevice");
  };

  // This device apart; the others one row per name, the latest first.
  const rows: DeviceRow[] = [];
  for (const session of [...sessions].sort((a, b) =>
    b.last_seen_at.localeCompare(a.last_seen_at),
  )) {
    const name = deviceName(session.device_label);
    const same = session.current
      ? undefined
      : rows.find((row) => !row.current && row.name === name);
    if (same) same.sessions.push(session);
    else
      rows.push({
        id: session.id,
        name,
        kind: describeDevice(session.device_label).kind,
        sessions: [session],
        current: session.current,
        lastSeen: session.last_seen_at,
      });
  }
  rows.sort((a, b) => Number(b.current) - Number(a.current));
  const others = sessions.filter((session) => !session.current).length;

  async function revoke(row: DeviceRow) {
    // The menu stays usable while a revoke runs; one at a time.
    if (revoking) return;
    setRevoking(row.id);
    setProblem(undefined);
    setNotice(undefined);
    try {
      for (const session of row.sessions) await revokeSession(session.id);
      if (row.current) {
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

  async function revokeOthers() {
    setEndingOthers(true);
    setProblem(undefined);
    setNotice(undefined);
    try {
      const ended = await revokeOtherSessions();
      setNotice(t("othersEnded", { count: ended }));
      await load();
    } catch (error) {
      setProblem(identityErrorMessage(error, problemMessages(identity)));
    } finally {
      setEndingOthers(false);
    }
  }

  const columns: ColumnDef<DeviceRow, unknown>[] = [
    {
      id: "device",
      accessorKey: "name",
      header: t("colDevice"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => {
        const Icon = DEVICE_ICONS[row.kind];
        return (
          <div className="flex items-center gap-3">
            <Icon
              aria-hidden="true"
              className="size-5 shrink-0 text-muted-foreground"
            />
            <p className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium">
              <span className="wrap-anywhere">{row.name}</span>
              {row.sessions.length > 1 ? (
                <span className="font-normal text-muted-foreground">
                  {t("sessionCount", { count: row.sessions.length })}
                </span>
              ) : null}
              {row.current ? (
                <Badge variant="secondary">{t("current")}</Badge>
              ) : null}
              {revoking === row.id ? (
                <span className="font-normal text-muted-foreground">
                  {t("ending")}
                </span>
              ) : null}
            </p>
          </div>
        );
      },
    },
    {
      id: "lastActive",
      accessorKey: "lastSeen",
      header: t("lastActive"),
      cell: ({ row: { original: row } }) => formatDate(row.lastSeen, locale),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={[
            {
              label: t("logout"),
              icon: <LogOutIcon aria-hidden="true" />,
              destructive: true,
              onSelect: () => void revoke(row),
            },
          ]}
          label={t("actionsFor", { device: row.name })}
        />
      ),
    },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-56">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {others ? (
            <Button
              disabled={endingOthers}
              onClick={() => void revokeOthers()}
              variant="outline"
            >
              <LogOutIcon aria-hidden="true" />
              {endingOthers ? t("endingOthers") : t("logoutOthers")}
            </Button>
          ) : null}
          <Button
            aria-label={t("refresh")}
            onClick={() => void load()}
            size="icon"
            title={t("refresh")}
            variant="ghost"
          >
            <RefreshCwIcon
              aria-hidden="true"
              className={loading ? "animate-spin" : ""}
            />
          </Button>
        </div>
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
        {notice ? (
          <p className="text-sm text-success-foreground" role="status">
            {notice}
          </p>
        ) : null}
        <DataTable
          caption={t("title")}
          columns={columns}
          data={showAll ? rows : rows.slice(0, SHOWN)}
          getRowId={(row) => row.id}
          labels={{ ...labels, empty: t("empty") }}
          loading={loading}
        />
        {rows.length > SHOWN ? (
          <Button
            aria-expanded={showAll}
            onClick={() => setShowAll(!showAll)}
            variant="ghost"
          >
            {showAll ? t("showFewer") : t("showAll", { count: rows.length })}
          </Button>
        ) : null}
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
