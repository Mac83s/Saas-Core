import "server-only";

import { cookies } from "next/headers";

import type {
  BookingOverview,
  CustomerBillingOverview,
  OrganizationSummary,
  UserSummary,
} from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function getServerUser(): Promise<UserSummary | null> {
  return serverGet<UserSummary>("/api/v1/auth/me/");
}

export async function getServerCurrentOrganization(): Promise<OrganizationSummary | null> {
  return serverGet<OrganizationSummary>("/api/v1/organizations/current/");
}

export async function getServerOrganizations(): Promise<OrganizationSummary[]> {
  return (
    (await serverGet<OrganizationSummary[]>("/api/v1/organizations/")) ?? []
  );
}

export async function getServerCustomerBillingOverview(): Promise<CustomerBillingOverview | null> {
  return serverGet<CustomerBillingOverview>("/api/v1/billing/overview/");
}

/** Who takes visits and what waits, for the menu (ADR-058); null without the calendar. */
export async function getServerBookingOverview(): Promise<BookingOverview | null> {
  return serverGet<BookingOverview>("/api/v1/booking/overview/");
}

async function serverGet<T>(path: string): Promise<T | null> {
  const cookieStore = await cookies();
  const response = await fetch(`${backendUrl}${path}`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  });
  if ([401, 403, 404, 409].includes(response.status)) return null;
  if (!response.ok)
    throw new Error(`Backend API ${path} zwróciło status ${response.status}`);
  return (await response.json()) as T;
}
