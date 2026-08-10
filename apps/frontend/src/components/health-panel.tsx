"use client";

import { useCallback, useEffect, useState } from "react";
import { ActivityIcon, RefreshCwIcon } from "lucide-react";

import { getHealth, type HealthStatus } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthStatus }
  | { kind: "error"; message: string };

export function HealthPanel() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const refresh = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", health: await getHealth() });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "Nieznany błąd API",
      });
    }
  }, []);

  useEffect(() => {
    let active = true;

    void getHealth()
      .then((health) => {
        if (active) setState({ kind: "ready", health });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "Nieznany błąd API",
        });
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <Card className="max-w-2xl">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <CardTitle className="flex items-center gap-2">
            <ActivityIcon aria-hidden="true" className="size-5" />
            Stan API
          </CardTitle>
          <CardDescription>
            Endpoint /api/v1/health/ przez proxy same-origin.
          </CardDescription>
        </div>
        <HealthBadge state={state} />
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <p aria-live="polite" className="text-muted-foreground text-sm">
          {state.kind === "loading" && "Sprawdzanie połączenia…"}
          {state.kind === "ready" &&
            `API ${state.health.status}; profil: ${state.health.deployment}`}
          {state.kind === "error" && state.message}
        </p>
        <Button onClick={() => void refresh()} size="sm" variant="outline">
          <RefreshCwIcon aria-hidden="true" data-icon="inline-start" />
          Odśwież
        </Button>
      </CardContent>
    </Card>
  );
}

function HealthBadge({ state }: { state: LoadState }) {
  if (state.kind === "loading")
    return <Badge variant="secondary">Sprawdzanie</Badge>;
  if (state.kind === "error")
    return <Badge variant="destructive">Niedostępne</Badge>;
  return <Badge>Połączono</Badge>;
}
