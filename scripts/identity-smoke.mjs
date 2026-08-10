import { randomUUID } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const baseUrl = new URL(
  process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080",
);
const emailDirectory = resolve(
  process.env.SAAS_CORE_EMAILS_DIR ?? ".runtime/emails",
);
const email = `identity-smoke-${randomUUID()}@example.test`;

const rejectedWithoutCsrf = await fetch(
  new URL("/api/v1/auth/register/", baseUrl),
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password: "Identity-Smoke-2026!",
      locale: "pl",
    }),
    signal: AbortSignal.timeout(5_000),
  },
);
const csrfProblem = await rejectedWithoutCsrf.json();
if (rejectedWithoutCsrf.status !== 403 || csrfProblem.code !== "csrf_failed") {
  throw new Error(
    `Brak CSRF nie został odrzucony jako Problem Details: HTTP ${rejectedWithoutCsrf.status}`,
  );
}
console.log(`OK wymagany CSRF: ${rejectedWithoutCsrf.status}`);

const csrfResponse = await fetch(new URL("/api/v1/auth/csrf/", baseUrl), {
  headers: { Accept: "application/json" },
  signal: AbortSignal.timeout(5_000),
});
const csrfPayload = await csrfResponse.json();
const cookieHeader = csrfResponse.headers.get("set-cookie");
const csrfCookie = cookieHeader?.match(/csrftoken=[^;]+/)?.[0];
if (!csrfResponse.ok || !csrfPayload.csrf_token || !csrfCookie) {
  throw new Error(`Nie udało się pobrać CSRF: HTTP ${csrfResponse.status}`);
}

const registration = await postJson("/api/v1/auth/register/", {
  email,
  password: "Identity-Smoke-2026!",
  locale: "pl",
});
if (registration.status !== 202) {
  throw new Error(
    `Rejestracja nie przeszła: HTTP ${registration.status} ${JSON.stringify(registration.payload)}`,
  );
}
console.log(`OK rejestracja asynchroniczna: ${registration.status}`);

const token = await waitForVerificationToken(email);
console.log("OK wiadomość weryfikacyjna z workera");

const confirmation = await postJson(
  "/api/v1/auth/email-verifications/confirm/",
  { token },
);
if (confirmation.status !== 200 || confirmation.payload.status !== "verified") {
  throw new Error(
    `Weryfikacja nie przeszła: HTTP ${confirmation.status} ${JSON.stringify(confirmation.payload)}`,
  );
}
console.log(`OK jednorazowa aktywacja: ${confirmation.status}`);

const replay = await postJson("/api/v1/auth/email-verifications/confirm/", {
  token,
});
if (replay.status !== 400) {
  throw new Error(`Ponowne użycie tokenu zwróciło HTTP ${replay.status}`);
}
console.log(`OK odrzucenie ponownego użycia tokenu: ${replay.status}`);

const loginResponse = await fetch(new URL("/api/v1/auth/login/", baseUrl), {
  method: "POST",
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
    Cookie: csrfCookie,
    "X-CSRFToken": csrfPayload.csrf_token,
  },
  body: JSON.stringify({ email, password: "Identity-Smoke-2026!" }),
  signal: AbortSignal.timeout(5_000),
});
const loginPayload = await loginResponse.json();
if (loginResponse.status !== 200 || loginPayload.email !== email) {
  throw new Error(`Logowanie nie przeszło: HTTP ${loginResponse.status}`);
}
const browserCookies = new Map([["csrftoken", csrfCookie.split("=")[1]]]);
for (const setCookie of loginResponse.headers.getSetCookie()) {
  const [pair] = setCookie.split(";", 1);
  const separator = pair.indexOf("=");
  browserCookies.set(pair.slice(0, separator), pair.slice(separator + 1));
}
const authenticatedCookie = [...browserCookies]
  .map(([name, value]) => `${name}=${value}`)
  .join("; ");
const authenticatedCsrf = browserCookies.get("csrftoken");
if (!authenticatedCsrf || browserCookies.size < 2) {
  throw new Error("Login nie zwrócił kompletu cookies CSRF i sesji");
}
console.log("OK login i rotacja cookies sesji");

const meResponse = await fetch(new URL("/api/v1/auth/me/", baseUrl), {
  headers: { Accept: "application/json", Cookie: authenticatedCookie },
  signal: AbortSignal.timeout(5_000),
});
if (meResponse.status !== 200 || (await meResponse.json()).email !== email) {
  throw new Error(`Endpoint me nie przeszedł: HTTP ${meResponse.status}`);
}
const sessionsResponse = await fetch(
  new URL("/api/v1/auth/sessions/", baseUrl),
  {
    headers: { Accept: "application/json", Cookie: authenticatedCookie },
    signal: AbortSignal.timeout(5_000),
  },
);
const sessions = await sessionsResponse.json();
if (
  sessionsResponse.status !== 200 ||
  sessions.length !== 1 ||
  !sessions[0].current
) {
  throw new Error(`Lista sesji nie przeszła: HTTP ${sessionsResponse.status}`);
}
console.log("OK me i lista aktywnych sesji");

const logoutResponse = await fetch(new URL("/api/v1/auth/logout/", baseUrl), {
  method: "POST",
  headers: {
    Cookie: authenticatedCookie,
    "X-CSRFToken": authenticatedCsrf,
  },
  signal: AbortSignal.timeout(5_000),
});
if (logoutResponse.status !== 204) {
  throw new Error(`Logout nie przeszedł: HTTP ${logoutResponse.status}`);
}
const stolenCookieReplay = await fetch(new URL("/api/v1/auth/me/", baseUrl), {
  headers: { Cookie: authenticatedCookie },
  signal: AbortSignal.timeout(5_000),
});
if (stolenCookieReplay.status !== 403) {
  throw new Error(
    `Unieważnione cookie nadal działa: HTTP ${stolenCookieReplay.status}`,
  );
}
console.log("OK logout i odrzucenie unieważnionego cookie");
console.log(`Smoke Identity zakończony: ${baseUrl}`);

async function postJson(path, payload) {
  const response = await fetch(new URL(path, baseUrl), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: csrfCookie,
      "X-CSRFToken": csrfPayload.csrf_token,
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(5_000),
  });
  return { status: response.status, payload: await response.json() };
}

async function waitForVerificationToken(recipient) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const files = await readdir(emailDirectory);
    for (const file of files) {
      const message = await readFile(resolve(emailDirectory, file), "utf8");
      if (!message.includes(recipient)) continue;
      const match = message.match(/verify-email\?token=([A-Za-z0-9._~-]+)/);
      if (match) return match[1];
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  }
  throw new Error(
    `Worker nie zapisał wiadomości dla ${recipient} w ciągu 30 sekund`,
  );
}
