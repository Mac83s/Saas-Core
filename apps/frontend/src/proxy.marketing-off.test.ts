import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }),
}));
// A deployment that shows no marketing of the core on its platform host.
vi.mock("./marketing/enabled", () => ({ marketingSiteEnabled: false }));

import proxy from "./proxy";

function visit(path: string, host = "localhost:8080") {
  return proxy(
    new NextRequest(`http://localhost${path}`, { headers: { host } }),
  );
}

describe("proxy on a platform host without marketing (features.marketingSite)", () => {
  it.each([
    ["/", "/login"],
    ["/pl", "/login"],
    ["/en", "/en/login"],
  ])("sends %s to sign-in", async (path, target) => {
    const response = await visit(path);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      `http://localhost:8080${target}`,
    );
  });

  it.each([
    "/pricing",
    "/contact",
    "/en/pricing",
    "/katalog",
    "/katalog/mragowo/salon",
    "/regulamin",
  ])("answers the marketing address %s with 404", async (path) => {
    expect((await visit(path)).status).toBe(404);
  });

  it.each([
    "/login",
    "/en/register",
    "/panel/sites",
    "/settings/security",
    "/invitations/abc",
    "/book/salon",
    "/en/booking/abc",
    "/documents/regulamin",
    "/sitemap.xml",
  ])("leaves the panel's and a guest's page %s alone", async (path) => {
    expect((await visit(path)).status).toBe(200);
  });

  it("still renders a customer's site on its own host", async () => {
    const response = await visit("/pricing", "studio.example.test");
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "http://localhost/site-renderer/pricing",
    );
  });
});
