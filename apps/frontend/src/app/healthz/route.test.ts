import { afterEach, describe, expect, it, vi } from "vitest";

import { deployment } from "../../generated/deployment";

const loadRoute = async () => {
  vi.resetModules();
  return import("./route");
};

const backendHealth = (profileHash: string | undefined) =>
  vi.fn(async () =>
    Response.json({ status: "ok", deployment: "x", profile_hash: profileHash }),
  );

afterEach(() => {
  vi.unstubAllGlobals();
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

  it("pamięta niezgodność, bo błąd budowania sam się nie naprawi", async () => {
    vi.stubGlobal("fetch", backendHealth("sha256:z-innego-drzewa"));
    const { GET } = await loadRoute();
    await GET();

    // Backend wraca ze zgodnym hashem — to znaczy, że podmieniono go pod nami,
    // a nie że ten obraz nagle stał się właściwy.
    vi.stubGlobal("fetch", backendHealth(deployment.profileHash));

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
