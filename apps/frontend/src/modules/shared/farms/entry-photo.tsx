"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { getFarmHealthPhoto } from "@saas-core/api-client";

/**
 * Zdjęcie dołączone do wpisu kartoteki.
 *
 * Plik nie jest kopią: leży w magazynie tej organizacji, która go zrobiła, a
 * rejestr wchodzi do niego przez wpis (decyzja z 20.09). Adres istnieje tylko
 * tak długo, jak długo miniatura jest na ekranie — bajty nie trafiają do
 * historii przeglądarki ani do pamięci podręcznej.
 */
export function EntryPhoto({
  entryId,
  mediaId,
}: {
  entryId: string;
  mediaId: string;
}) {
  const t = useTranslations("Animals");
  const [url, setUrl] = useState<string>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    let objectUrl: string | undefined;
    getFarmHealthPhoto(entryId, mediaId, abort.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        // Autor mógł zdjęcie usunąć albo cofnięto udział — jedno i drugie
        // znaczy to samo: tego zdjęcia już nie ma dla nas.
        if (!abort.signal.aborted) setFailed(true);
      });
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [entryId, mediaId]);

  if (failed) {
    return (
      <span className="rounded-lg border border-dashed px-2 py-1 text-xs text-muted-foreground">
        {t("photoUnavailable")}
      </span>
    );
  }
  if (!url) {
    return (
      <span
        aria-label={t("photoLoading")}
        className="size-20 animate-pulse rounded-lg bg-muted"
        role="img"
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- adres blob żyje
    // tylko w tej karcie; optymalizator Next musiałby go pobrać z serwera.
    <img
      alt={t("photoAlt")}
      className="size-20 rounded-lg object-cover"
      src={url}
    />
  );
}
