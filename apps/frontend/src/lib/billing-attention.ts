import type { CustomerSubscription } from "@saas-core/api-client";

/**
 * The design shows the subscription in the menu only when it needs the
 * owner's attention; an active plan shows nothing. Computed on the server, so
 * "days left" does not differ between the render and hydration.
 */
export type BillingAttention =
  | { kind: "trial"; days: number | null }
  | { kind: "payment" | "limited" | "noPlan" | "canceled" };

const DAY_MS = 24 * 60 * 60 * 1000;

export function billingAttention(
  subscription: CustomerSubscription | null | undefined,
  now: number,
): BillingAttention | null {
  // Access comes first: a plan canceled and run out keeps state "canceled"
  // and only drops to read-only, which is what the owner has to hear about.
  if (
    subscription?.access_mode === "read_only" ||
    subscription?.access_mode === "blocked"
  )
    return { kind: "limited" };
  switch (subscription?.state) {
    case undefined:
    case "unconfigured":
      return { kind: "noPlan" };
    case "trialing":
      return {
        kind: "trial",
        // Whole days left, so the last day reads "ends today", not "1 day".
        days: subscription.trial_end
          ? Math.max(
              0,
              Math.floor((Date.parse(subscription.trial_end) - now) / DAY_MS),
            )
          : null,
      };
    case "grace_period":
      return { kind: "payment" };
    case "canceled":
      return { kind: "canceled" };
    case "read_only":
    case "suspended":
      return { kind: "limited" };
    default:
      return null;
  }
}
