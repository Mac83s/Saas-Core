import { spawnSync } from "node:child_process";

const baseUrl = new URL(
  process.env.SAAS_CORE_BASE_URL ?? "http://127.0.0.1:8080",
);

try {
  compose("stop", "redis");
  await waitFor(
    "/api/v1/health/",
    (status, payload) =>
      status === 503 &&
      payload.status === "degraded" &&
      payload.checks?.cache === "error",
    "readiness po zatrzymaniu Redis",
  );
  await waitFor(
    "/api/v1/health/live/",
    (status, payload) => status === 200 && payload.checks?.process === "ok",
    "liveness po zatrzymaniu Redis",
  );
  console.log("OK awaria Redis: readiness=503, liveness=200");
} finally {
  compose("up", "-d", "--wait", "--wait-timeout", "90", "redis");
}

await waitFor(
  "/api/v1/health/",
  (status, payload) => status === 200 && payload.status === "ok",
  "readiness po odtworzeniu Redis",
);

try {
  compose("stop", "backend");
  await waitForStatus(
    "/api/v1/health/live/",
    new Set([502, 503]),
    "API po zatrzymaniu backendu",
  );
  await waitFor(
    "/healthz",
    (status) => status === 200,
    "frontend przy zatrzymanym backendzie",
  );
  console.log("OK awaria backendu: API niedostępne, frontend health działa");
} finally {
  compose("up", "-d", "--wait", "--wait-timeout", "90", "backend");
}

try {
  compose("stop", "frontend");
  await waitForStatus(
    "/healthz",
    new Set([502, 503]),
    "frontend po zatrzymaniu upstreamu",
  );
  await waitFor(
    "/api/v1/health/live/",
    (status, payload) => status === 200 && payload.checks?.process === "ok",
    "API przy zatrzymanym frontendzie",
  );
  console.log("OK awaria frontendu: panel niedostępny, API działa");
} finally {
  compose("up", "-d", "--wait", "--wait-timeout", "90", "frontend");
}

try {
  compose("stop", "worker");
  await waitFor(
    "/api/v1/health/",
    (status, payload) => status === 200 && payload.status === "ok",
    "API przy zatrzymanym workerze",
  );
  console.log("OK awaria workera: synchroniczne API nadal odpowiada");
} finally {
  compose("up", "-d", "--wait", "--wait-timeout", "90", "worker");
}

console.log("Failure smoke zakończony, usługi zostały odtworzone");

function compose(...args) {
  const result = spawnSync("docker", ["compose", ...args], {
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `docker compose ${args.join(" ")} zakończył się kodem ${result.status}`,
    );
  }
}

async function waitFor(path, predicate, label) {
  let lastResult = "brak odpowiedzi";
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(new URL(path, baseUrl), {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(3_000),
      });
      const payload = await response.json();
      lastResult = `HTTP ${response.status} ${JSON.stringify(payload)}`;
      if (predicate(response.status, payload)) return;
    } catch (error) {
      lastResult = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} nie osiągnął oczekiwanego stanu: ${lastResult}`);
}

async function waitForStatus(path, statuses, label) {
  let lastStatus = "brak odpowiedzi";
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(new URL(path, baseUrl), {
        signal: AbortSignal.timeout(3_000),
      });
      lastStatus = `HTTP ${response.status}`;
      if (statuses.has(response.status)) return;
    } catch (error) {
      lastStatus = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} nie osiągnął oczekiwanego stanu: ${lastStatus}`);
}
