import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

// A profile with a guest language beyond the panel's two (TL17).
vi.mock("./generated/deployment", async (original) => {
  const { deployment } =
    await original<typeof import("./generated/deployment")>();
  return {
    deployment: {
      ...deployment,
      product: { ...deployment.product, supportedLocales: ["pl", "en", "de"] },
    },
  };
});

import proxy from "./proxy";

function visit(path: string, headers: Record<string, string> = {}) {
  return proxy(
    new NextRequest(`http://localhost${path}`, {
      headers: { host: "localhost:8080", ...headers },
    }),
  );
}

describe("language route groups (TL17)", () => {
  it("serves a guest page in its address's language, and only by its address", () => {
    const german = visit("/de/katalog", { "accept-language": "en" });

    expect(german.status).toBe(200);
    // No cookie, no Link header: the URL alone says the language.
    expect(german.headers.getSetCookie()).toEqual([]);
    expect(german.headers.get("link")).toBeNull();
  });

  it("answers the root in the default language whatever the browser says", () => {
    const root = visit("/", { "accept-language": "en-GB,en;q=0.9" });

    expect(root.status).toBe(200);
    expect(root.headers.get("location")).toBeNull();
    expect(root.headers.getSetCookie()).toEqual([]);
  });

  it("spells a guest address canonically with a permanent redirect", () => {
    const polish = visit("/pl/katalog");

    expect(polish.status).toBe(308);
    expect(new URL(polish.headers.get("location")!).pathname).toBe("/katalog");
  });

  it("sends a guest language in front of the panel to the panel's English, permanently", () => {
    const panel = visit("/de/panel/settings?tab=team");

    expect(panel.status).toBe(308);
    expect(panel.headers.get("location")).toBe(
      "http://localhost:8080/en/panel/settings?tab=team",
    );
    expect(visit("/de/login").headers.get("location")).toBe(
      "http://localhost:8080/en/login",
    );
  });

  it("keeps a redirect that follows the person's language temporary", () => {
    // A cached 308 would keep sending someone who switched back to Polish.
    const detected = visit("/panel", { cookie: "NEXT_LOCALE=en" });

    expect(detected.status).toBe(307);
    expect(new URL(detected.headers.get("location")!).pathname).toBe(
      "/en/panel",
    );
  });

  it("drops the default prefix from a panel address permanently", () => {
    const prefixed = visit("/pl/panel");

    expect(prefixed.status).toBe(308);
    expect(new URL(prefixed.headers.get("location")!).pathname).toBe("/panel");
    expect(visit("/en/panel").status).toBe(200);
  });

  it("books in a guest language", () => {
    expect(visit("/de/book/salon-anna").status).toBe(200);
  });
});
