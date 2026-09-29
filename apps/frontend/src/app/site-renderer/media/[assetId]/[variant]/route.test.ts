import { beforeEach, expect, test, vi } from "vitest";
import { GET } from "./route";

const fixture = vi.hoisted(() => ({
  getPublicMedia: vi.fn(),
  headers: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: fixture.headers }));
vi.mock("../../../../../modules/shared/sites/public-projection", () => ({
  getPublicMedia: fixture.getPublicMedia,
}));
const assetId = "019ff20d-d000-7000-8000-000000000002";

beforeEach(() => {
  vi.resetAllMocks();
  fixture.headers.mockResolvedValue(
    new Headers({ host: "customer.example.test" }),
  );
});

test("a published picture's WebP copy comes from the host-scoped backend", async () => {
  fixture.getPublicMedia.mockResolvedValue({
    kind: "media",
    body: Buffer.from("RIFF0000WEBP"),
    contentType: "image/webp",
    cacheControl: "public, max-age=31536000, immutable",
  });
  const response = await GET(new Request("https://customer.example.test/"), {
    params: Promise.resolve({ assetId, variant: "preview" }),
  });
  expect(fixture.getPublicMedia).toHaveBeenCalledWith(
    "customer.example.test",
    assetId,
    "preview",
  );
  expect(response.status).toBe(200);
  expect(response.headers.get("content-type")).toBe("image/webp");
});

test("only the pipeline's two copies are asked for", async () => {
  for (const variant of ["original", "../x", "Preview"]) {
    const response = await GET(new Request("https://customer.example.test/"), {
      params: Promise.resolve({ assetId, variant }),
    });
    expect(response.status).toBe(404);
  }
  expect(fixture.getPublicMedia).not.toHaveBeenCalled();
});
