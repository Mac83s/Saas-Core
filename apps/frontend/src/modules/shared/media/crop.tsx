"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { uploadImage } from "./capture";

/** Ile pikseli ma dłuższy bok kadru; tyle wystarcza pierwszemu ekranowi strony. */
const CROP_EDGE = 1600;

/**
 * Wycina z obrazu prostokąt widoczny w ramce i oddaje go jako plik.
 *
 * Ramka ma proporcję miejsca docelowego, obraz jest w niej skalowany „cover”,
 * a `offset` mówi, którą część widać: 0 to lewa krawędź albo góra, 1 to prawa
 * albo dół. Liczymy w pikselach oryginału, żeby kadr nie tracił na jakości
 * przez podwójne skalowanie.
 */
export async function cropImage(
  file: File,
  {
    aspect,
    zoom = 1,
    offsetX = 0.5,
    offsetY = 0.5,
    quality = 0.85,
  }: {
    aspect: readonly [number, number];
    zoom?: number;
    offsetX?: number;
    offsetY?: number;
    quality?: number;
  },
): Promise<File> {
  const bitmap = await createImageBitmap(file, {
    imageOrientation: "from-image",
  });
  const wanted = aspect[0] / aspect[1];
  const source = bitmap.width / bitmap.height;
  // Największy prostokąt o żądanej proporcji, jaki mieści się w obrazie,
  // pomniejszony o przybliżenie.
  const baseWidth = source > wanted ? bitmap.height * wanted : bitmap.width;
  const baseHeight = source > wanted ? bitmap.height : bitmap.width / wanted;
  const width = baseWidth / zoom;
  const height = baseHeight / zoom;
  const left = (bitmap.width - width) * offsetX;
  const top = (bitmap.height - height) * offsetY;

  const scale = Math.min(1, CROP_EDGE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Przeglądarka nie dała kontekstu 2D.");
  context.drawImage(
    bitmap,
    left,
    top,
    width,
    height,
    0,
    0,
    canvas.width,
    canvas.height,
  );
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", quality),
  );
  if (!blob) throw new Error("Nie udało się zakodować kadru.");
  const name = file.name.replace(/\.[^.]+$/, "") || "obraz";
  return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
}

/**
 * Wgrywanie obrazu w miejsce, które ma swój kształt: blok strony, logo, sekcja.
 *
 * Kadr jest tu, a nie po stronie serwera, bo to operator widzi, co na zdjęciu
 * jest ważne. Wysyłamy sam kadr — oryginał i tak nie zostaje w systemie po
 * przetworzeniu, a przy okazji na łącze idzie ułamek pliku z aparatu.
 */
export function ImageCropUpload({
  aspect,
  label,
  onUploaded,
}: {
  aspect: readonly [number, number];
  label: string;
  onUploaded: (assetId: string) => void;
}) {
  const t = useTranslations("MediaCrop");
  // Plik i jego adres razem: adres powstaje przy wyborze, a nie w efekcie,
  // który dokładałby kolejne przejście renderowania po każdym wyborze.
  const [picked, setPicked] = useState<{ file: File; url: string }>();
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0.5, y: 0.5 });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const dragging = useRef<{ x: number; y: number } | null>(null);

  // Sprzątanie adresu blob w jednym miejscu: przy wyborze następnego zdjęcia i
  // przy zamknięciu okna, także bez kliknięcia „Anuluj”.
  const url = picked?.url;
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );

  function reset() {
    setPicked(undefined);
    setZoom(1);
    setOffset({ x: 0.5, y: 0.5 });
    setFailed(false);
  }

  // Przeciąganie przesuwa kadr o tyle, o ile obraz wystaje poza ramkę: przy
  // zoomie 1 i proporcji zgodnej z obrazem nie ma czym ruszać i tak jest dobrze.
  function drag(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragging.current || !frame.current) return;
    const box = frame.current.getBoundingClientRect();
    const dx = (event.clientX - dragging.current.x) / box.width;
    const dy = (event.clientY - dragging.current.y) / box.height;
    dragging.current = { x: event.clientX, y: event.clientY };
    setOffset((current) => ({
      x: Math.min(1, Math.max(0, current.x - dx)),
      y: Math.min(1, Math.max(0, current.y - dy)),
    }));
  }

  async function send() {
    if (!picked) return;
    setBusy(true);
    setFailed(false);
    try {
      const cropped = await cropImage(picked.file, {
        aspect,
        zoom,
        offsetX: offset.x,
        offsetY: offset.y,
      });
      const { file } = picked;
      const asset = await uploadImage(
        cropped,
        `crop:${file.name}:${file.size}:${file.lastModified}:${aspect.join("x")}`,
      );
      onUploaded(asset.id);
      reset();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <label className="inline-flex h-9 cursor-pointer items-center rounded-md border px-3 text-sm">
        {label}
        <input
          accept="image/*"
          className="sr-only"
          onChange={(event) => {
            const chosen = event.target.files?.[0];
            event.target.value = "";
            if (chosen)
              setPicked({ file: chosen, url: URL.createObjectURL(chosen) });
          }}
          type="file"
        />
      </label>

      <Dialog onOpenChange={(open) => !open && reset()} open={Boolean(picked)}>
        <DialogContent closeLabel={t("close")}>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>
              {t("description", { width: aspect[0], height: aspect[1] })}
            </DialogDescription>
          </DialogHeader>

          <div
            className="relative w-full overflow-hidden rounded-lg bg-muted"
            onPointerDown={(event) => {
              dragging.current = { x: event.clientX, y: event.clientY };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={drag}
            onPointerUp={() => (dragging.current = null)}
            ref={frame}
            style={{ aspectRatio: `${aspect[0]} / ${aspect[1]}` }}
          >
            {picked ? (
              /* Adres blob żyje tylko w tym oknie; optymalizator Next
                 pobrałby go z serwera, którego nie zna. */
              // eslint-disable-next-line @next/next/no-img-element
              <img
                alt={t("preview")}
                className="absolute inset-0 size-full object-cover"
                src={picked.url}
                style={{
                  objectPosition: `${offset.x * 100}% ${offset.y * 100}%`,
                  transform: `scale(${zoom})`,
                }}
              />
            ) : null}
          </div>

          <Field>
            <FieldLabel htmlFor="media-crop-zoom">{t("zoom")}</FieldLabel>
            <Input
              id="media-crop-zoom"
              max={3}
              min={1}
              onChange={(event) => setZoom(Number(event.target.value))}
              step={0.1}
              type="range"
              value={zoom}
            />
          </Field>

          {failed ? (
            <p className="text-sm text-destructive" role="alert">
              {t("failed")}
            </p>
          ) : null}

          <div className="flex gap-2">
            <Button disabled={busy} onClick={send}>
              {busy ? t("sending") : t("send")}
            </Button>
            <Button disabled={busy} onClick={reset} variant="outline">
              {t("cancel")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
