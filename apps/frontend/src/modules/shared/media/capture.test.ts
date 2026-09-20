import { describe, expect, test, vi } from "vitest";

const api = vi.hoisted(() => ({
  initiateMediaUpload: vi.fn(),
  completeMediaUpload: vi.fn(),
}));
vi.mock("@saas-core/api-client", () => api);

import { compressImage, uploadImage } from "./capture";

describe("zdjęcie z telefonu", () => {
  test("zmniejsza dłuższy bok i wychodzi jako JPEG", async () => {
    // Zdjęcie 3000×2000 z aparatu; do dokumentacji wystarcza 1600 px.
    const bitmap = { width: 3000, height: 2000, close: vi.fn() };
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(async () => bitmap),
    );
    const context = { drawImage: vi.fn() };
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => context,
      toBlob: (done: (blob: Blob) => void) => done(new Blob(["x"])),
    };
    vi.spyOn(document, "createElement").mockReturnValue(
      canvas as unknown as HTMLCanvasElement,
    );

    const out = await compressImage(
      new File([new Uint8Array(4_000_000)], "IMG_0421.HEIC", {
        type: "image/heic",
      }),
    );

    expect([canvas.width, canvas.height]).toEqual([1600, 1067]);
    expect(bitmap.close).toHaveBeenCalled();
    expect(out.type).toBe("image/jpeg");
    expect(out.name).toBe("IMG_0421.jpg");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("wgranie to intencja, magazyn i domknięcie", async () => {
    api.initiateMediaUpload.mockResolvedValue({
      asset: { id: "asset-1" },
      upload_url: "https://magazyn.example/put",
      upload_headers: { "Content-Type": "image/jpeg" },
    });
    api.completeMediaUpload.mockResolvedValue({
      id: "asset-1",
      state: "uploaded",
    });
    const fetchMock = vi.fn(async () => ({ ok: true }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["x"], "zdjecie.jpg", { type: "image/jpeg" });

    const asset = await uploadImage(file, "klucz-1");

    expect(api.initiateMediaUpload).toHaveBeenCalledWith(
      { filename: "zdjecie.jpg", content_type: "image/jpeg", size: file.size },
      "klucz-1",
    );
    expect(fetchMock).toHaveBeenCalledWith("https://magazyn.example/put", {
      method: "PUT",
      headers: { "Content-Type": "image/jpeg" },
      body: file,
    });
    expect(asset.id).toBe("asset-1");
    vi.unstubAllGlobals();
  });

  test("odmowa magazynu nie udaje sukcesu", async () => {
    api.initiateMediaUpload.mockResolvedValue({
      asset: { id: "asset-2" },
      upload_url: "https://magazyn.example/put",
      upload_headers: {},
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 507 })),
    );

    await expect(
      uploadImage(new File(["x"], "a.jpg", { type: "image/jpeg" }), "klucz-2"),
    ).rejects.toThrow("507");
    expect(api.completeMediaUpload).not.toHaveBeenCalledWith("asset-2");
    vi.unstubAllGlobals();
  });
});
