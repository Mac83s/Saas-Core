"use client";

import {
  completeMediaUpload,
  initiateMediaUpload,
  type MediaAsset,
} from "@saas-core/api-client";

/**
 * Zdjęcie z telefonu, przygotowane do wysłania.
 *
 * Aparat w telefonie robi dziś 4–12 MB; w gospodarstwie z jedną kreską zasięgu
 * taki plik nie dojedzie, a do dokumentacji wystarcza ułamek tego. Zmniejszamy
 * dłuższy bok i przekodowujemy do JPEG — bez kadrowania, bo zdjęcie z pracy ma
 * pokazać to, co widział korektor, a przycięcie odbiera informację (decyzja z
 * 20.09). Kadr należy do zdjęć wchodzących w układ strony, nie do tych.
 *
 * Przy okazji znika EXIF: `createImageBitmap` obraca obraz zgodnie z zapisaną
 * orientacją, a canvas zapisuje same piksele — więc ze zdjęciem nie wyjeżdża
 * lokalizacja gospodarstwa ani model telefonu.
 */
export async function compressImage(
  file: File,
  { maxEdge = 1600, quality = 0.8 }: { maxEdge?: number; quality?: number } = {},
): Promise<File> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Przeglądarka nie dała kontekstu 2D.");
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", quality),
  );
  if (!blob) throw new Error("Nie udało się zakodować zdjęcia.");
  const name = file.name.replace(/\.[^.]+$/, "") || "zdjecie";
  return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
}

/**
 * Wgrywa przygotowany plik i zwraca zasób, gdy magazyn go przyjął.
 *
 * Trzy kroki API mediów w jednym: intencja, wysyłka do magazynu, domknięcie.
 * Stan zasobu na końcu to `uploaded` — skan i przetworzenie idą w tle, więc
 * wywołujący dostaje identyfikator od razu i nie czeka na miniaturę.
 */
export async function uploadImage(
  file: File,
  idempotencyKey: string,
): Promise<MediaAsset> {
  const intent = await initiateMediaUpload(
    { filename: file.name, content_type: file.type, size: file.size },
    idempotencyKey,
  );
  const stored = await fetch(intent.upload_url, {
    method: "PUT",
    headers: intent.upload_headers,
    body: file,
  });
  if (!stored.ok) throw new Error(`Magazyn odpowiedział ${stored.status}.`);
  return completeMediaUpload(intent.asset.id);
}
