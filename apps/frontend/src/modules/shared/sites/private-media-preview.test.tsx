import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PrivateMediaPreview } from "./private-media-preview";

const { getMediaAssetPreview } = vi.hoisted(() => ({
  getMediaAssetPreview: vi.fn(),
}));
vi.mock("@saas-core/api-client", () => ({ getMediaAssetPreview }));
const create = vi.fn(() => "blob:private-preview");
const revoke = vi.fn();
beforeEach(() => {
  vi.resetAllMocks();
  create.mockReturnValue("blob:private-preview");
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const view = (assetId = "asset-one", locale = "pl") => (
  <NextIntlClientProvider
    locale={locale}
    messages={locale === "pl" ? polishMessages : englishMessages}
  >
    <PrivateMediaPreview assetId={assetId} alt="Zdjęcie gabinetu" />
  </NextIntlClientProvider>
);

test("uses an authenticated blob, updates alt text and revokes it on unmount", async () => {
  getMediaAssetPreview.mockResolvedValue(
    new Blob(["webp"], { type: "image/webp" }),
  );
  const rendered = render(view());
  expect(screen.getByRole("status")).toHaveTextContent("Ładowanie zdjęcia");
  const image = await screen.findByRole("img");
  expect(image).toHaveAttribute("src", "blob:private-preview");
  expect(image).toHaveAttribute("alt", "Zdjęcie gabinetu");
  const signal = getMediaAssetPreview.mock.calls[0][1] as AbortSignal;
  expect(getMediaAssetPreview.mock.calls[0][0]).toBe("asset-one");
  rendered.unmount();
  expect(signal.aborted).toBe(true);
  expect(revoke).toHaveBeenCalledWith("blob:private-preview");
});

test("ignores a late response after changing the asset", async () => {
  let resolveOld!: (blob: Blob) => void;
  getMediaAssetPreview
    .mockImplementationOnce(
      () =>
        new Promise<Blob>((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValueOnce(new Blob(["new"]));
  const rendered = render(view());
  const signal = getMediaAssetPreview.mock.calls[0][1] as AbortSignal;
  rendered.rerender(view("asset-two"));
  await screen.findByRole("img");
  await act(async () => resolveOld(new Blob(["old"])));
  expect(signal.aborted).toBe(true);
  expect(create).toHaveBeenCalledTimes(1);
});

test.each(["pl", "en"])(
  "failed fetch and decode can be retried (%s)",
  async (locale) => {
    getMediaAssetPreview
      .mockRejectedValueOnce(new Error("forbidden"))
      .mockResolvedValue(new Blob(["webp"]));
    render(view("asset-one", locale));
    const retry = locale === "pl" ? "Spróbuj ponownie" : "Try again";
    fireEvent.click(await screen.findByRole("button", { name: retry }));
    fireEvent.error(await screen.findByRole("img"));
    fireEvent.click(await screen.findByRole("button", { name: retry }));
    await screen.findByRole("img");
    await waitFor(() => expect(getMediaAssetPreview).toHaveBeenCalledTimes(3));
    expect(revoke).toHaveBeenCalledWith("blob:private-preview");
  },
);
