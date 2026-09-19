import { ApiProblemError } from "@saas-core/api-client";

/** Why a read failed, and therefore what the person can do about it. */
export type FarmProblem = "load" | "access" | "plan" | "missing";

export function farmProblemKind(error: unknown): FarmProblem {
  if (!(error instanceof ApiProblemError)) return "load";
  const { code, status } = error.problem;
  if (code === "entitlement_required") return "plan";
  if (status === 403) return "access";
  if (status === 404) return "missing";
  return "load";
}

/**
 * The first human sentence of a Problem Details answer. A validation error
 * carries `{field: [message]}` in `detail`; show its first message rather than
 * the generic title.
 */
export function farmProblem(error: unknown, fallback: string): string {
  if (!(error instanceof ApiProblemError)) return fallback;
  const detail: unknown = error.problem.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    for (const value of Object.values(detail)) {
      const first: unknown = Array.isArray(value) ? value[0] : value;
      if (typeof first === "string") return first;
    }
  }
  return fallback;
}
