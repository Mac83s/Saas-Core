import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The locale middleware is next-intl's; these tests are about what the proxy
// decides before it hands a platform page over.
vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }),
}));

// The backend's word on an address gone for good; none by default.
const gone = vi.hoisted(() => ({ goneVerdict: vi.fn() }));
vi.mock("./modules/shared/sites/gone-check", () => gone);

import {
  GONE_HOME_HEADER,
  GONE_LOCALE_HEADER,
} from "./modules/shared/sites/gone-headers";
import proxy, {
  PUBLIC_SITE_PATH_HEADER,
  PUBLIC_SITE_TRAILING_SLASH_HEADER,
} from "./proxy";

const forwarded = (response: Response, header: string) =>
  response.headers.get(`x-middleware-request-${header}`);

function visit(
  url: string,
  host: string,
  headers: Record<string, string> = {},
) {
  return proxy(new NextRequest(url, { headers: { host, ...headers } }));
}

beforeEach(() => {
  gone.goneVerdict.mockReset();
  gone.goneVerdict.mockResolvedValue({ gone: false });
});

describe("proxy (ADR-071)", () => {
  it("passes a customer site's path as typed, slash included", async () => {
    const withSlash = await visit(
      "http://studio.example.test/oferta/",
      "studio.example.test",
    );
    expect(withSlash.headers.get("x-middleware-rewrite")).toBe(
      "http://studio.example.test/site-renderer/oferta/",
    );
    expect(forwarded(withSlash, PUBLIC_SITE_PATH_HEADER)).toBe("/oferta/");
    expect(forwarded(withSlash, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("1");

    const without = await visit(
      "http://studio.example.test/oferta",
      "studio.example.test",
    );
    expect(forwarded(without, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("0");
    const root = await visit(
      "http://studio.example.test/",
      "studio.example.test",
    );
    expect(forwarded(root, PUBLIC_SITE_TRAILING_SLASH_HEADER)).toBe("0");
  });

  it("answers the platform's own pages without the slash, in one 308", async () => {
    const response = await visit(
      "http://localhost/pricing/?plan=pro",
      "localhost:8080",
    );
    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8080/pricing?plan=pro",
    );
  });

  it.each(["localhost", "studio.example.test"])(
    "refuses the renderer asked for directly on %s",
    async (host) => {
      for (const path of ["/site-renderer", "/site-renderer/oferta/"]) {
        expect((await visit(`http://${host}${path}`, host)).status).toBe(404);
      }
    },
  );
});

describe("proxy: an address gone for good (ADR-077)", () => {
  it("hands it to the 410 page with the backend's language, not the visitor's", async () => {
    gone.goneVerdict.mockResolvedValue({
      gone: true,
      locale: "ru",
      homePath: "/ru/",
    });
    const response = await visit(
      "http://studio.example.test/ru/%D0%BF%D0%BE%D1%80%D0%BE%D0%B4%D1%8B/?utm=1",
      "studio.example.test",
      { [GONE_LOCALE_HEADER]: "xx", [GONE_HOME_HEADER]: "https://evil.test/" },
    );
    // Asked with the path as the page's params would spell it.
    expect(gone.goneVerdict).toHaveBeenCalledWith(
      "studio.example.test",
      "/ru/породы/",
    );
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "http://studio.example.test/site-gone",
    );
    expect(forwarded(response, GONE_LOCALE_HEADER)).toBe("ru");
    expect(forwarded(response, GONE_HOME_HEADER)).toBe("/ru/");
  });

  it("asks only about pages, and never on the platform's own host", async () => {
    await visit("http://studio.example.test/rss.xml", "studio.example.test");
    await visit("http://localhost/pricing", "localhost:8080");
    await proxy(
      new NextRequest("http://studio.example.test/kontakt/", {
        method: "POST",
        headers: { host: "studio.example.test" },
      }),
    );
    expect(gone.goneVerdict).not.toHaveBeenCalled();
  });

  it("refuses the 410 page asked for directly on the platform host", async () => {
    expect(
      (await visit("http://localhost/site-gone", "localhost")).status,
    ).toBe(404);
  });
});
