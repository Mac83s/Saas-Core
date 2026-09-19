"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getMediaAssetPreview } from "@saas-core/api-client";
import type { BlockImageRenderer } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";

/** URLs exist only while mounted; image bytes never enter the draft or history. */
export const renderPrivateMedia: BlockImageRenderer = (image) => (
  <PrivateMediaPreview
    key={image.asset_id}
    assetId={image.asset_id}
    alt={image.alt}
  />
);

export function PrivateMediaPreview({
  assetId,
  alt,
}: {
  assetId: string;
  alt: string;
}) {
  const t = useTranslations("Sites.studio");
  const [attempt, setAttempt] = useState(0);
  return (
    <PreviewRequest
      key={`${assetId}:${attempt}`}
      assetId={assetId}
      alt={alt}
      loadingLabel={t("imageLoading")}
      errorLabel={t("imageUnavailable")}
      retryLabel={t("imageRetry")}
      onRetry={() => setAttempt((value) => value + 1)}
    />
  );
}

function PreviewRequest({
  assetId,
  alt,
  loadingLabel,
  errorLabel,
  retryLabel,
  onRetry,
}: {
  assetId: string;
  alt: string;
  loadingLabel: string;
  errorLabel: string;
  retryLabel: string;
  onRetry: () => void;
}) {
  const [url, setUrl] = useState<string>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    getMediaAssetPreview(assetId, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetId]);
  if (failed)
    return (
      <div
        role="status"
        className="flex min-h-32 flex-col items-center justify-center gap-2 rounded border border-dashed p-4 text-sm"
      >
        <span>{errorLabel}</span>
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          {retryLabel}
        </Button>
      </div>
    );
  if (!url)
    return (
      <div
        role="status"
        className="flex min-h-32 items-center justify-center rounded bg-muted p-4 text-sm"
      >
        {loadingLabel}
      </div>
    );
  // The authenticated API supplies a processed WebP blob, never a public URL.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} decoding="async" onError={() => setFailed(true)} />
  );
}
