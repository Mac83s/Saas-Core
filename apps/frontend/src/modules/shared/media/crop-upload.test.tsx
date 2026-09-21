import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

const upload = vi.hoisted(() => ({ uploadImage: vi.fn() }));
vi.mock("./capture", () => upload);

import polishMessages from "../../../../messages/pl.json";
import { ImageCropUpload } from "./crop";

afterEach(() => {
  // Odmontowanie zwalnia adres blob, więc cleanup musi wyprzedzić przywrócenie
  // globali — inaczej komponent woła metodę, której już nie ma.
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function view(onUploaded = vi.fn()) {
  // Kadr liczy canvas, którego jsdom nie ma; geometrii pilnuje crop.test.ts.
  const context = { drawImage: vi.fn() };
  vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
    tag === "canvas"
      ? ({
          width: 0,
          height: 0,
          getContext: () => context,
          toBlob: (done: (blob: Blob) => void) => done(new Blob(["kadr"])),
        } as unknown as HTMLCanvasElement)
      : Object.getPrototypeOf(document).createElement.call(
          document,
          tag,
        )) as typeof document.createElement);
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => ({ width: 1200, height: 900, close: vi.fn() })),
  );
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = () => "blob:kadr";
      static revokeObjectURL = () => undefined;
    },
  );
  render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <ImageCropUpload
        aspect={[16, 9]}
        label="Wgraj i skadruj"
        onUploaded={onUploaded}
      />
    </NextIntlClientProvider>,
  );
  return { onUploaded };
}

test("kadr otwiera się z proporcją miejsca i wysyła wycięty plik", async () => {
  upload.uploadImage.mockResolvedValue({ id: "asset-kadr" });
  const { onUploaded } = view();

  fireEvent.change(screen.getByLabelText("Wgraj i skadruj"), {
    target: {
      files: [new File(["oryginał"], "panorama.png", { type: "image/png" })],
    },
  });

  // Okno mówi wprost, w jakiej proporcji miejsce pokaże zdjęcie.
  expect(
    await screen.findByRole("dialog", { name: "Kadr zdjęcia" }),
  ).toBeVisible();
  expect(screen.getByText(/16:9/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Wytnij i wyślij" }));

  await waitFor(() => expect(upload.uploadImage).toHaveBeenCalledTimes(1));
  const [sent] = upload.uploadImage.mock.calls[0]!;
  // Na serwer idzie kadr, nie plik wybrany z dysku.
  expect((sent as File).type).toBe("image/jpeg");
  expect((sent as File).name).toBe("panorama.jpg");
  expect(onUploaded).toHaveBeenCalledWith("asset-kadr");
  // Po wysłaniu okno znika, a pole jest gotowe na następne zdjęcie.
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("nieudana wysyłka zostawia okno otwarte i mówi o błędzie", async () => {
  upload.uploadImage.mockRejectedValue(new Error("brak sieci"));
  const { onUploaded } = view();

  fireEvent.change(screen.getByLabelText("Wgraj i skadruj"), {
    target: { files: [new File(["x"], "a.png", { type: "image/png" })] },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Wytnij i wyślij" }),
  );

  expect(
    await screen.findByText("Nie udało się wysłać zdjęcia."),
  ).toBeInTheDocument();
  expect(onUploaded).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeVisible();
});
