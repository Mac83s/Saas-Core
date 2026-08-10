import { ApiProblemError } from "@saas-core/api-client";

export type IdentityProblemMessages = {
  invalidCredentials: string;
  invalidMfaCode: string;
  mfaSetupRequired: string;
  apiUnavailable: string;
};

export function identityErrorMessage(
  error: unknown,
  messages: IdentityProblemMessages,
): string {
  if (error instanceof ApiProblemError) {
    if (error.problem.code === "invalid_credentials") {
      return messages.invalidCredentials;
    }
    if (error.problem.code === "invalid_mfa_code") {
      return messages.invalidMfaCode;
    }
    if (error.problem.code === "mfa_setup_required") {
      return messages.mfaSetupRequired;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : messages.apiUnavailable;
}

export function identityFieldError(
  error: unknown,
  field: string,
): string | undefined {
  if (!(error instanceof ApiProblemError)) return undefined;
  const detail = error.problem.detail;
  if (typeof detail !== "object" || detail === null || !(field in detail)) {
    return undefined;
  }
  const messages = (detail as Record<string, unknown>)[field];
  if (!Array.isArray(messages) || messages.length === 0) return undefined;
  const first = messages[0];
  if (typeof first === "string") return first;
  if (typeof first === "object" && first !== null && "message" in first) {
    const message = (first as { message?: unknown }).message;
    return typeof message === "string" ? message : undefined;
  }
  return undefined;
}
