const baseUrl = new URL(
  process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080",
);

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
if (!panel.includes("Lokalny runtime platformy działa")) {
  throw new Error("panel nie zawiera oczekiwanego znacznika W2");
}
console.log(`OK panel: ${panelResponse.status}`);

console.log(`Smoke runtime zakończony: ${baseUrl}`);

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
