import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fixtureDeployment,
  fixtureOldAddresses,
  fixtureSite,
} from "#lib/product-site/fixture";
import { describeResponse } from "./proxy-corpus";

/**
 * `/media/…` on the platform's host: the pictures of the platform's own
 * published content (ADR-079 pkt 30). The block renderers write a picture's
 * address relative to the host their page is on; a product's pages are on
 * the platform's, a company's site on its own — whose `/media/…` must
 * answer exactly as it did.
 */
const asset = "019ff20d-d000-7000-8000-000000000002";

async function load(product: boolean) {
  vi.resetModules();
  vi.doMock("./generated/deployment", () => ({
    deployment: fixtureDeployment({ marketingSite: !product }),
  }));
  vi.doMock("./product/public-site", () => ({
    publicSite: product ? fixtureSite : null,
  }));
  vi.doMock("./product/old-addresses", () => ({
    oldAddresses: product ? fixtureOldAddresses : {},
  }));
  const { default: proxy } = await import("./proxy");
  return (address: string, host = "platform.example.test") =>
    describeResponse(
      proxy(new NextRequest(`http://${host}${address}`, { headers: { host } })),
    );
}

afterEach(() => {
  vi.doUnmock("./generated/deployment");
  vi.doUnmock("./product/public-site");
  vi.doUnmock("./product/old-addresses");
  vi.resetModules();
});

describe.each([
  ["with a product's own public pages", true],
  ["with the core's marketing pages", false],
])("the platform's media, %s", (_name, product) => {
  it("hands a picture and its two copies to the app route, untouched", async () => {
    const visit = await load(product);

    expect(visit(`/media/${asset}`)).toBe("200 next");
    expect(visit(`/media/${asset}/thumbnail`)).toBe("200 next");
    expect(visit(`/media/${asset}/preview`)).toBe("200 next");
    expect(visit(`/media/${asset.toUpperCase()}`)).toBe("200 next");
    // The other spelling is one 308, as for every address of this host.
    expect(visit(`/media/${asset}/`)).toBe(
      `308 location=http://platform.example.test/media/${asset}`,
    );
  });

  it("hands nothing else under /media to the app route", async () => {
    const visit = await load(product);

    for (const address of [
      "/media",
      "/media/abc",
      `/media/${asset}/original`,
      `/media/${asset}/preview/more`,
      `/en/media/${asset}`,
      `/media/${asset.slice(1)}`,
    ]) {
      // Whatever this profile answers an address nobody has — a 404, or the
      // locale middleware's own — as before the rule.
      expect(visit(address)).not.toBe("200 next");
    }
  });

  it("leaves a company's own /media to its renderer", async () => {
    const visit = await load(product);
    const host = "studio.example.test";

    for (const address of [`/media/${asset}`, `/media/${asset}/preview`]) {
      expect(visit(address, host)).toBe(
        `200 rewrite=http://${host}/site-renderer${address} ` +
          `request[x-saas-core-site-method=GET, x-saas-core-site-path=${address}, ` +
          "x-saas-core-site-trailing-slash=0]",
      );
    }
  });
});
