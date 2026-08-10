import { ApiProblemError } from "@saas-core/api-client";

export function organizationErrorMessage(
  error: unknown,
  fallback: string,
): string {
  if (error instanceof ApiProblemError) return error.message;
  return error instanceof Error ? error.message : fallback;
}
