import { spawnSync } from "node:child_process";
import { request as httpRequest } from "node:http";

const baseUrl = new URL(
  process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080",
);

for (const service of ["backend", "worker", "worker-ai", "scheduler"]) {
  checkDatabaseRole(service);
}
checkMalwareScanner();

await checkJson("frontend", "/healthz", (payload) => payload.status === "ok");
await checkJson(
  "API liveness",
  "/api/v1/health/live/",
  (payload) => payload.status === "ok" && payload.checks?.process === "ok",
  true,
);
await checkJson(
  "API readiness",
  "/api/v1/health/",
  (payload) =>
    payload.status === "ok" &&
    payload.checks?.database === "ok" &&
    payload.checks?.cache === "ok",
  true,
);
await checkStatus(
  "prywatny endpoint autoryzacji TLS",
  "/internal/caddy/domains/authorize/?domain=arbitrary.example.test",
  404,
);
await checkStatus(
  "nieprzypisany publiczny host",
  "/",
  404,
  "unclaimed.example.test",
);

const panelResponse = await fetch(new URL("/", baseUrl), {
  headers: { Accept: "text/html" },
  signal: AbortSignal.timeout(5_000),
});
if (!panelResponse.ok) {
  throw new Error(`panel zwrócił HTTP ${panelResponse.status}`);
}
const panel = await panelResponse.text();
if (!panel.includes("Bezpieczny fundament Twojego produktu SaaS")) {
  throw new Error("panel nie zawiera oczekiwanego znacznika W3");
}
console.log(`OK panel: ${panelResponse.status}`);

console.log(`Smoke runtime zakończony: ${baseUrl}`);

function checkDatabaseRole(service) {
  const result = spawnSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      service,
      "python",
      "manage.py",
      "check_database_role",
    ],
    { stdio: "inherit" },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${service} używa uprzywilejowanej roli PostgreSQL`);
  }
}

function checkMalwareScanner() {
  const result = spawnSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "worker",
      "python",
      "manage.py",
      "check_malware_scanner",
    ],
    { stdio: "inherit" },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error("worker nie ma działającego połączenia z ClamAV");
  }
}

async function checkJson(label, path, predicate, correlationRequired = false) {
  const response = await fetch(new URL(path, baseUrl), {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(5_000),
  });
  const payload = await response.json();
  if (!response.ok || !predicate(payload)) {
    throw new Error(
      `${label} nie przeszedł: HTTP ${response.status} ${JSON.stringify(payload)}`,
    );
  }
  if (correlationRequired) {
    const header = response.headers.get("x-correlation-id");
    if (!header || header !== payload.correlation_id) {
      throw new Error(`${label} ma niespójny correlation ID`);
    }
  }
  console.log(`OK ${label}: ${response.status}`);
}

async function checkStatus(label, path, expectedStatus, host) {
  const status = await requestStatus(new URL(path, baseUrl), host);
  if (status !== expectedStatus) {
    throw new Error(
      `${label} zwrócił HTTP ${status}, oczekiwano ${expectedStatus}`,
    );
  }
  console.log(`OK ${label}: ${status}`);
}

function requestStatus(url, host) {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      url,
      {
        headers: {
          Accept: "text/html,application/json",
          ...(host ? { Host: host } : {}),
        },
      },
      (response) => {
        response.resume();
        resolve(response.statusCode ?? 0);
      },
    );
    request.setTimeout(5_000, () =>
      request.destroy(new Error(`timeout dla ${url}`)),
    );
    request.on("error", reject);
    request.end();
  });
}
