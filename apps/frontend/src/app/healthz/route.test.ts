import { afterEach, describe, expect, it, vi } from "vitest";

import { deployment } from "../../generated/deployment";
import { RECHECK_AFTER_MS } from "./recheck";

const loadRoute = async () => {
  vi.resetModules();
  return import("./route");
};

const backendHealth = (profileHash: string | undefined) =>
  vi.fn(async () =>
    Response.json({ status: "ok", deployment: "x", profile_hash: profileHash }),
  );

const start = Date.parse("2026-10-03T12:00:00Z");

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("healthz", () => {
  it("odpowiada ok, gdy oba obrazy pochodzą z tego samego drzewa", async () => {
    vi.stubGlobal("fetch", backendHealth(deployment.profileHash));

    const { GET } = await loadRoute();
    const response = await GET();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ status: "ok" });
  });

  it("odmawia, gdy backend niesie inny hash profilu", async () => {
    vi.stubGlobal("fetch", backendHealth("sha256:z-innego-drzewa"));

    const { GET } = await loadRoute();
    const response = await GET();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      status: "profile_mismatch",
    });
  });

  it("nie pyta ponownie o niezgodność przed upływem odstępu", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: start });
    const fetch = backendHealth("sha256:z-innego-drzewa");
    vi.stubGlobal("fetch", fetch);
    const { GET } = await loadRoute();
    await GET();

    vi.setSystemTime(start + RECHECK_AFTER_MS - 1);

    expect((await GET()).status).toBe(503);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("zdrowieje, gdy po przebudowie obu obrazów wstaje zgodny backend", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: start });
    // Nowy frontend wstał, gdy odpowiadał jeszcze stary backend.
    vi.stubGlobal("fetch", backendHealth("sha256:stary-backend"));
    const { GET } = await loadRoute();
    expect((await GET()).status).toBe(503);

    vi.stubGlobal("fetch", backendHealth(deployment.profileHash));
    vi.setSystemTime(start + RECHECK_AFTER_MS);

    expect((await GET()).status).toBe(200);
  });

  it("trwałą niezgodność zgłasza dalej, z chwilą pierwszego wykrycia", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: start });
    vi.stubGlobal("fetch", backendHealth("sha256:z-innego-drzewa"));
    const { GET } = await loadRoute();
    await GET();

    vi.setSystemTime(start + 3 * RECHECK_AFTER_MS);
    const response = await GET();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      status: "profile_mismatch",
      since: new Date(start).toISOString(),
    });
  });

  it("milczący backend nie kasuje wykrytej niezgodności", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: start });
    vi.stubGlobal("fetch", backendHealth("sha256:z-innego-drzewa"));
    const { GET } = await loadRoute();
    await GET();

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );
    vi.setSystemTime(start + RECHECK_AFTER_MS);

    expect((await GET()).status).toBe(503);
  });

  it("nie przewraca się, gdy backend milczy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );

    const { GET } = await loadRoute();
    const response = await GET();

    expect(response.status).toBe(200);
  });

  it("nie przewraca się, gdy backend nie podaje hasha", async () => {
    vi.stubGlobal("fetch", backendHealth(undefined));

    const { GET } = await loadRoute();

    expect((await GET()).status).toBe(200);
  });
});
