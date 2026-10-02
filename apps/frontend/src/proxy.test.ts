import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

// The locale middleware is next-intl's; these tests are about what the proxy
// decides before it hands a platform page over.
vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }),
}));

import proxy, {
  PUBLIC_SITE_PATH_HEADER,
  PUBLIC_SITE_TRAILING_SLASH_HEADER,
} from "./proxy";

const forwarded = (response: Response, header: string) =>
  response.headers.get(`x-middleware-request-${header}`);

function visit(url: string, host: string) {
  return proxy(new NextRequest(url, { headers: { host } }));
}

describe("proxy (ADR-071)", () => {
  it("passes a customer site's path as typed, slash included", () => {
    const withSlash = visit(
      "http://studio.example.test/oferta/",
      "studio.example.test",
    );
    expect(withSlash.headers.get("x-middleware-rewrite")).toBe(
      "http://studio.example.test/site-renderer/oferta/",
    );
    expect(forwarded(withSlash, PUBLIC_SITE_PATH_HEADER)).toBe("/oferta/");
    expect(forwarded(withSlash, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("1");

    const without = visit(
      "http://studio.example.test/oferta",
      "studio.example.test",
    );
    expect(forwarded(without, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("0");
    const root = visit("http://studio.example.test/", "studio.example.test");
    expect(forwarded(root, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("0");
  });

  it("answers the platform's own pages without the slash, in one 308", () => {
    const response = visit("http://localhost/pricing/?plan=pro", "localhost");
    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("/pricing?plan=pro");
  });

  it.each(["localhost", "studio.example.test"])(
    "refuses the renderer asked for directly on %s",
    (host) => {
      for (const path of ["/site-renderer", "/site-renderer/oferta/"]) {
        expect(visit(`http://${host}${path}`, host).status).toBe(404);
      }
    },
  );
});
