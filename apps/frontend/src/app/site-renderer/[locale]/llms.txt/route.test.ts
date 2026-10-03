import { beforeEach, expect, test, vi } from "vitest";
import { GET } from "./route";

const fixture = vi.hoisted(() => ({
  getPublicProjection: vi.fn(),
  headers: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: fixture.headers }));
vi.mock("../../../../modules/shared/sites/public-projection", () => ({
  getPublicProjection: fixture.getPublicProjection,
}));

beforeEach(() => {
  vi.resetAllMocks();
  fixture.headers.mockResolvedValue(
    new Headers({ host: "customer.example.test" }),
  );
});

test("a language's llms.txt is the backend's in that language", async () => {
  fixture.getPublicProjection.mockResolvedValue({
    kind: "xml",
    body: "# Studio",
    contentType: "text/plain; charset=utf-8",
  });
  const response = await GET(
    new Request("https://customer.example.test/en/llms.txt"),
    { params: Promise.resolve({ locale: "en" }) },
  );
  expect(fixture.getPublicProjection).toHaveBeenCalledWith(
    "customer.example.test",
    "llms.txt",
    "en",
  );
  expect(response.status).toBe(200);
  expect(await response.text()).toBe("# Studio");
});

test("anything but a language code is not an llms.txt address", async () => {
  const response = await GET(
    new Request("https://customer.example.test/blog/llms.txt"),
    { params: Promise.resolve({ locale: "blog" }) },
  );
  expect(response.status).toBe(404);
  expect(fixture.getPublicProjection).not.toHaveBeenCalled();
});
