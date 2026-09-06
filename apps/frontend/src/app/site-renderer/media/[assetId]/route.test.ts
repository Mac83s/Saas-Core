import { beforeEach, expect, test, vi } from "vitest";
import { GET } from "./route";

const fixture = vi.hoisted(() => ({
  getPublicMedia: vi.fn(),
  headers: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: fixture.headers }));
vi.mock("../../../../modules/shared/sites/public-projection", () => ({
  getPublicMedia: fixture.getPublicMedia,
}));
const assetId = "019ff20d-d000-7000-8000-000000000002";

beforeEach(() => {
  vi.resetAllMocks();
  fixture.headers.mockResolvedValue(
    new Headers({ host: "customer.example.test" }),
  );
});

test("published image bytes and cache policy come from the host-scoped backend", async () => {
  const content = Buffer.from([137, 80, 78, 71]);
  fixture.getPublicMedia.mockResolvedValue({
    kind: "media",
    body: content,
    contentType: "image/png",
    cacheControl: "public, max-age=31536000, immutable",
  });
  const response = await GET(
    new Request("https://customer.example.test/media/" + assetId),
    { params: Promise.resolve({ assetId }) },
  );
  expect(fixture.getPublicMedia).toHaveBeenCalledWith(
    "customer.example.test",
    assetId,
  );
  expect(response.status).toBe(200);
  expect(response.headers.get("content-type")).toBe("image/png");
  expect(response.headers.get("cache-control")).toBe(
    "public, max-age=31536000, immutable",
  );
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(
    new Uint8Array(content),
  );
});

test("a foreign or unpublished image remains a 404", async () => {
  fixture.getPublicMedia.mockResolvedValue({ kind: "not-found" });
  expect(
    (
      await GET(new Request("https://other.example.test/media/" + assetId), {
        params: Promise.resolve({ assetId }),
      })
    ).status,
  ).toBe(404);
});

test("malformed asset identifiers do not reach the backend", async () => {
  expect(
    (
      await GET(new Request("https://customer.example.test/media/invalid"), {
        params: Promise.resolve({ assetId: "../invalid" }),
      })
    ).status,
  ).toBe(404);
  expect(fixture.getPublicMedia).not.toHaveBeenCalled();
});
