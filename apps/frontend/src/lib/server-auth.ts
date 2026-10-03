import "server-only";

import { cookies } from "next/headers";

import type {
  BookingOverview,
  CustomerBillingOverview,
  OrganizationSummary,
  SettingOptions,
  SettingsSchema,
  UserSummary,
} from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function getServerUser(): Promise<UserSummary | null> {
  return serverGet<UserSummary>("/api/v1/auth/me/");
}

export async function getServerCurrentOrganization(): Promise<OrganizationSummary | null> {
  return serverGet<OrganizationSummary>("/api/v1/organizations/current/");
}

/**
 * Whether the active company refuses this account until it turns on
 * two-factor sign-in (owner answer 35a): the API answers every company request
 * with `organization_mfa_required` until then.
 */
export async function getServerOrganizationRequiresMfa(): Promise<boolean> {
  const cookieStore = await cookies();
  const response = await fetch(`${backendUrl}/api/v1/organizations/current/`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  });
  if (response.status !== 403) return false;
  const problem = (await response.json().catch(() => null)) as {
    code?: string;
  } | null;
  return problem?.code === "organization_mfa_required";
}

/** Every settings group the company has, with what it may choose (ADR-078). */
export async function getServerSettingsSchema(): Promise<SettingsSchema | null> {
  return serverGet<SettingsSchema>(
    "/api/v1/organizations/current/settings/schema/",
  );
}

/** What a company may choose for its basic settings (ADR-078). */
export async function getServerOrganizationOptions(): Promise<SettingOptions | null> {
  return serverGet<SettingOptions>("/api/v1/organizations/options/");
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

/** The company's languages behind a public booking page; null when there is
 *  no such page (the form says so itself). */
export async function getServerPublicBookingLocales(
  publicSlug: string,
): Promise<string[] | null> {
  const catalog = await serverGet<{ locales?: string[] }>(
    `/api/v1/booking/public/${encodeURIComponent(publicSlug)}/`,
  );
  return catalog?.locales ?? null;
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
