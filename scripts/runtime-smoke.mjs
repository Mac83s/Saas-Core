import { spawnSync } from "node:child_process";

const baseUrl = new URL(
  process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080",
);

for (const service of ["backend", "worker", "scheduler"]) {
  checkDatabaseRole(service);
}

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
