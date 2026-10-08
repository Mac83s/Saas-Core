import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { platformMedia } from "./media";

const asset = "019ff20d-d000-7000-8000-000000000002";
const png = new Uint8Array([137, 80, 78, 71]);
const fetched = vi.fn();

function answer(status: number, contentType = "image/png") {
  return new Response(status === 200 ? png : null, {
    status,
    headers: {
      "content-type": contentType,
      "cache-control": "public, max-age=31536000, immutable",
    },
  });
}

beforeEach(() => {
  fetched.mockReset();
  vi.stubGlobal("fetch", fetched);
});
afterEach(() => vi.unstubAllGlobals());

describe("a picture of the platform's content at /media (ADR-079)", () => {
  it("asks the read that takes no host, and marks the bytes as a picture only", async () => {
    fetched.mockResolvedValue(answer(200));

    const response = await platformMedia("localhost:8080", asset);

    expect(String(fetched.mock.calls[0]![0])).toBe(
      `http://127.0.0.1:8000/api/v1/public/content/media/${asset}/`,
    );
    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(png);
    expect(Object.fromEntries(response.headers)).toEqual({
      "content-type": "image/png",
      "cache-control": "public, max-age=31536000, immutable",
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'none'; sandbox",
    });
  });

  it("asks for a WebP copy by its name", async () => {
    fetched.mockResolvedValue(answer(200, "image/webp"));

    const response = await platformMedia("localhost", asset, "preview");

    expect(String(fetched.mock.calls[0]![0])).toBe(
      `http://127.0.0.1:8000/api/v1/public/content/media/${asset}/preview/`,
    );
    expect(response.headers.get("content-type")).toBe("image/webp");
  });

  it("is a 404 for what the backend does not show", async () => {
    fetched.mockResolvedValue(answer(404));

    expect((await platformMedia("localhost", asset)).status).toBe(404);
  });

  it("never asks the backend at a host that is not the platform's", async () => {
    for (const host of [
      "studio.example.test",
      "",
      null,
      "evil.test@localhost",
    ]) {
      expect((await platformMedia(host, asset)).status).toBe(404);
    }
    expect(fetched).not.toHaveBeenCalled();
  });

  it("never asks for anything but an asset id and the two copies", async () => {
    for (const [id, variant] of [
      ["abc", undefined],
      [`${asset}/../../v1/sites`, undefined],
      [`${asset}.png`, undefined],
      [asset, "original"],
      [asset, "../preview"],
      [asset, ""],
    ] as const) {
      expect((await platformMedia("localhost", id, variant)).status).toBe(404);
    }
    expect(fetched).not.toHaveBeenCalled();
  });

  it("serves no document from the panel's origin, whatever the storage holds", async () => {
    for (const type of ["text/html", "image/svg+xml", "application/pdf", ""]) {
      fetched.mockResolvedValue(answer(200, type));
      expect((await platformMedia("localhost", asset)).status).toBe(404);
    }
  });

  it("does not hide a backend that fails behind a missing picture", async () => {
    fetched.mockResolvedValue(answer(500));

    await expect(platformMedia("localhost", asset)).rejects.toThrow("500");
  });
});
