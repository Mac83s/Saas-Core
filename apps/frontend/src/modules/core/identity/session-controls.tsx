"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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

import { identityErrorMessage } from "./problem";

export function LogoutButton() {
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
      {pending ? "Wylogowanie…" : "Wyloguj"}
    </Button>
  );
}

export function SessionManager() {
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
      setProblem(identityErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [router]);

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
        setProblem(identityErrorMessage(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [router]);

  async function revoke(session: SessionSummary) {
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
      setProblem(identityErrorMessage(error));
    } finally {
      setRevoking(undefined);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Aktywne urządzenia</CardTitle>
          <CardDescription>
            Unieważnienie natychmiast blokuje wskazane cookie sesji.
          </CardDescription>
        </div>
        <Button
          aria-label="Odśwież sesje"
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
        {!loading && sessions.length === 0 && (
          <p className="text-sm text-muted-foreground">Brak aktywnych sesji.</p>
        )}
        {sessions.map((session) => (
          <div
            className="flex items-center gap-3 rounded-lg border p-3"
            key={session.id}
          >
            {/mobile|android|iphone/i.test(session.device_label) ? (
              <SmartphoneIcon
                aria-hidden="true"
                className="size-5 text-muted-foreground"
              />
            ) : (
              <LaptopIcon
                aria-hidden="true"
                className="size-5 text-muted-foreground"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-medium">
                  {session.device_label}
                </p>
                {session.current && <Badge variant="secondary">Ta sesja</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">
                Ostatnia aktywność: {formatDate(session.last_seen_at)}
              </p>
            </div>
            <Button
              disabled={revoking === session.id}
              onClick={() => void revoke(session)}
              size="sm"
              variant={session.current ? "destructive" : "outline"}
            >
              {revoking === session.id ? "Kończenie…" : "Wyloguj"}
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
