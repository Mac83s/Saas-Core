import "server-only";

import { cookies } from "next/headers";

import type { UserSummary } from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function getServerUser(): Promise<UserSummary | null> {
  const cookieStore = await cookies();
  const response = await fetch(`${backendUrl}/api/v1/auth/me/`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  });
  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok)
    throw new Error(`Identity API zwróciło status ${response.status}`);
  return (await response.json()) as UserSummary;
}
