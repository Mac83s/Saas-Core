import { spawnSync } from "node:child_process";

const baseUrl = process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080";
const grafanaUrl = process.env.SAAS_CORE_GRAFANA_URL ?? "http://127.0.0.1:3001";

await expectOk(`${baseUrl}/api/v1/health/live/`, "API liveness");

const metrics = await fetch(`${baseUrl}/internal/metrics/`).then(
  async (response) => {
    if (!response.ok)
      throw new Error(`metryki Django: HTTP ${response.status}`);
    return response.text();
  },
);
if (!metrics.includes("saas_core_http_requests_total")) {
  throw new Error("Brak metryk HTTP Django");
}

const grafana = await fetchJsonWithRetry(
  `${grafanaUrl}/api/health`,
  "Grafana health",
);
if (grafana.database !== "ok")
  throw new Error(`Grafana database=${grafana.database}`);

const targets = containerJson(
  "http://prometheus:9090/api/v1/targets?state=active",
);
const requiredJobs = new Set([
  "alloy",
  "caddy",
  "celery",
  "django",
  "loki",
  "postgres",
  "redis",
]);
for (const target of targets.data.activeTargets) {
  if (target.health === "up") requiredJobs.delete(target.labels.job);
}
if (requiredJobs.size) {
  throw new Error(`Niezdrowe cele Prometheus: ${[...requiredJobs].join(", ")}`);
}

const celeryMetrics = containerText("http://celery-exporter:9808/metrics");
if (!/saas_core_celery_workers\s+1(?:\.0)?$/m.test(celeryMetrics)) {
  throw new Error("Exporter Celery nie widzi dokładnie jednego workera");
}

await new Promise((resolve) => setTimeout(resolve, 2_000));
const loki = containerJson(
  "http://loki:3100/loki/api/v1/query_range?query=%7Bjob%3D%22saas-core%22%7D&limit=20",
);
if (!loki.data.result.length)
  throw new Error("Loki nie zawiera logów SaaS Core");

console.log(
  "Observability smoke OK: metryki, 7 targetów, Celery, Loki i Grafana",
);

async function expectOk(url, label) {
  const response = await fetch(url, { signal: AbortSignal.timeout(5_000) });
  if (!response.ok) throw new Error(`${label}: HTTP ${response.status}`);
}

async function fetchJsonWithRetry(url, label) {
  let lastError;
  for (let attempt = 1; attempt <= 15; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(5_000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      if (attempt < 15)
        await new Promise((resolve) => setTimeout(resolve, 2_000));
    }
  }
  throw new Error(`${label} nie odpowiada po 30 s`, { cause: lastError });
}

function containerJson(url) {
  return JSON.parse(containerText(url));
}

function containerText(url) {
  const code = [
    "import urllib.request",
    `print(urllib.request.urlopen(${JSON.stringify(url)}, timeout=5).read().decode())`,
  ].join("; ");
  const result = spawnSync(
    "docker",
    ["compose", "exec", "-T", "backend", "python", "-c", code],
    { encoding: "utf8" },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Zapytanie wewnętrzne nie powiodło się: ${result.stderr}`);
  }
  return result.stdout;
}
