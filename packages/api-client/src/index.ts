import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

const client = createClient<paths>({ baseUrl: "" });

export type HealthStatus = components["schemas"]["Health"];
export type UserSummary = components["schemas"]["UserSummary"];
export type SessionSummary = components["schemas"]["SessionSummary"];
export type RegistrationInput = components["schemas"]["Registration"];
export type LoginInput = components["schemas"]["Login"];
export type PasswordResetRequestInput =
  components["schemas"]["PasswordResetRequest"];
export type PasswordResetConfirmInput =
  components["schemas"]["PasswordResetConfirm"];
export type ProblemDetails = components["schemas"]["ProblemDetails"];

export type LoginResult =
  | { kind: "authenticated"; user: UserSummary }
  | { kind: "mfa_required" };

export class ApiProblemError extends Error {
  constructor(public readonly problem: ProblemDetails) {
    super(problemMessage(problem));
    this.name = "ApiProblemError";
  }
}

export async function getHealth(): Promise<HealthStatus> {
  const { data, error, response } = await client.GET("/api/v1/health/");
  if (error || !data) {
    throw new Error(`Health API zwróciło status ${response.status}`);
  }
  return data;
}

export async function getCurrentUser(): Promise<UserSummary> {
  const { data, error, response } = await client.GET("/api/v1/auth/me/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function registerAccount(
  input: RegistrationInput,
): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/register/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function loginAccount(input: LoginInput): Promise<LoginResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST("/api/v1/auth/login/", {
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !data) throwProblem(error, response);
  if (response.status === 202) return { kind: "mfa_required" };
  return { kind: "authenticated", user: data as UserSummary };
}

export async function completeMfaLogin(code: string): Promise<UserSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/login/mfa/",
    {
      body: { code },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function logoutAccount(): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST("/api/v1/auth/logout/", {
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !response.ok) throwProblem(error, response);
}

export async function requestEmailVerification(email: string): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/email-verifications/resend/",
    {
      body: { email },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function confirmEmailVerification(token: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/email-verifications/confirm/",
    {
      body: { token },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
}

export async function requestPasswordReset(
  input: PasswordResetRequestInput,
): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/password-resets/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function confirmPasswordReset(
  input: PasswordResetConfirmInput,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/password-resets/confirm/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
}

export async function listSessions(): Promise<SessionSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/auth/sessions/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeSession(sessionId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/auth/sessions/{session_id}/",
    {
      params: { path: { session_id: sessionId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

async function getCsrfToken(): Promise<string> {
  const { data, error, response } = await client.GET("/api/v1/auth/csrf/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data.csrf_token;
}

function throwProblem(error: unknown, response: Response): never {
  if (isProblemDetails(error)) throw new ApiProblemError(error);
  throw new Error(`API zwróciło status ${response.status}`);
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "status" in value
  );
}

function problemMessage(problem: ProblemDetails): string {
  if (typeof problem.detail === "string") return problem.detail;
  return problem.title;
}
