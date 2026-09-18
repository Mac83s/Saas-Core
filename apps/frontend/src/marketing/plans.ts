import "server-only";

import type { PublicPlan } from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * Plans for the pricing page, read from billing on the server so the page is
 * indexed with its prices. Revalidated every few minutes: a price change shows
 * up without a deploy, and a crawler does not hit the backend on every visit.
 * An unreachable backend gives an empty list, and the page says so, rather than
 * failing the whole marketing site.
 */
export async function getPublicPlans(): Promise<PublicPlan[]> {
  try {
    const response = await fetch(`${backendUrl}/api/v1/billing/plans/`, {
      next: { revalidate: 300 },
    });
    if (!response.ok) return [];
    return (await response.json()) as PublicPlan[];
  } catch {
    return [];
  }
}

export function formatPrice(plan: PublicPlan, locale: string): string {
  return new Intl.NumberFormat(locale === "en" ? "en-GB" : "pl-PL", {
    style: "currency",
    currency: plan.currency,
    maximumFractionDigits: 0,
  }).format(plan.unit_amount_minor / 100);
}
