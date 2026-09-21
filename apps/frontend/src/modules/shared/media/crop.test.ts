import { describe, expect, test, vi } from "vitest";

vi.mock("@saas-core/api-client", () => ({
  initiateMediaUpload: vi.fn(),
  completeMediaUpload: vi.fn(),
}));

import { cropImage } from "./crop";

function withCanvas() {
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
  return { canvas, context };
}

function withBitmap(width: number, height: number) {
  const bitmap = { width, height, close: vi.fn() };
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => bitmap),
  );
  return bitmap;
}

const file = () => new File(["x"], "zdjecie.png", { type: "image/png" });

describe("kadr do proporcji miejsca", () => {
  test("z pionowego zdjęcia bierze pas 16:9, wyśrodkowany", async () => {
    const bitmap = withBitmap(1000, 2000);
    const { canvas, context } = withCanvas();

    const out = await cropImage(file(), { aspect: [16, 9] });

    // Najszerszy pas 16:9, jaki mieści się w 1000×2000, to 1000×562.
    const [, left, top, width, height] = context.drawImage.mock.calls[0]!;
    expect([width, Math.round(height as number)]).toEqual([1000, 563]);
    expect(left).toBe(0);
    // Wyśrodkowany w pionie: (2000 − 563) / 2.
    expect(Math.round(top as number)).toBe(719);
    expect([canvas.width, canvas.height]).toEqual([1000, 563]);
    expect(bitmap.close).toHaveBeenCalled();
    expect(out.type).toBe("image/jpeg");
    expect(out.name).toBe("zdjecie.jpg");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("przybliżenie zawęża kadr, a przesunięcie wybiera jego miejsce", async () => {
    withBitmap(2000, 1000);
    const { context } = withCanvas();

    await cropImage(file(), {
      aspect: [1, 1],
      zoom: 2,
      offsetX: 1,
      offsetY: 0,
    });

    const [, left, top, width, height] = context.drawImage.mock.calls[0]!;
    // Kwadrat 1000×1000 podzielony przez przybliżenie 2.
    expect([width, height]).toEqual([500, 500]);
    // Skrajnie w prawo i do góry.
    expect([left, top]).toEqual([1500, 0]);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("duży kadr schodzi do 1600 px dłuższego boku", async () => {
    withBitmap(6000, 4000);
    const { canvas } = withCanvas();

    await cropImage(file(), { aspect: [2, 1] });

    expect([canvas.width, canvas.height]).toEqual([1600, 800]);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
});
