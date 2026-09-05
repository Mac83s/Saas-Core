import { NextResponse } from "next/server";

import { deployment } from "../../generated/deployment";

export const dynamic = "force-dynamic";

/**
 * Liveness, plus the one thing this process cannot check about itself.
 *
 * Backend and frontend are separate images built from separate trees, so a
 * bundle compiled for one composition can meet an API compiled for another.
 * Nothing crashes: the panel renders a menu for a module whose routes answer
 * 404, which reads as a broken feature rather than a mismatched deploy. The
 * profile hash is what makes the two comparable.
 *
 * A definite mismatch is permanent — it is a build mistake and will not heal —
 * so it is remembered and the container stays unhealthy. Not being able to ask
 * is different: a backend that is down or still starting says nothing about
 * this bundle, and failing liveness for it would only turn one outage into two.
 */
let mismatch: string | null = null;

async function backendProfileHash(): Promise<string | null> {
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(new URL("/api/v1/health/", backend), {
      cache: "no-store",
      signal: AbortSignal.timeout(2_000),
    });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    const hash =
      typeof payload === "object" && payload !== null
        ? (payload as { profile_hash?: unknown }).profile_hash
        : undefined;
    return typeof hash === "string" && hash.length > 0 ? hash : null;
  } catch {
    return null;
  }
}

export async function GET() {
  if (mismatch === null) {
    const backendHash = await backendProfileHash();
    if (backendHash !== null && backendHash !== deployment.profileHash) {
      mismatch = backendHash;
    }
  }

  if (mismatch !== null) {
    return NextResponse.json(
      {
        status: "profile_mismatch",
        detail:
          "Obraz frontendu i backendu pochodzą z różnych drzew: " +
          `frontend ${deployment.profileHash}, backend ${mismatch}.`,
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  return NextResponse.json(
    { status: "ok", deployment: deployment.id },
    { headers: { "Cache-Control": "no-store" } },
  );
}
