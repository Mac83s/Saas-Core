import { siteUiTexts } from "@saas-core/site-blocks";

type Photo = {
  thumbnail_url: string;
  preview_url: string;
  width: number;
  height: number;
  ai_generated: boolean;
};

/**
 * A unit's picture on a catalogue page: the server's own WebP copies at the
 * booking form's address, with the size the picture states and — for one a
 * model made — the visible „AI” mark and the same words in its `alt`
 * (ADR-059 pkt 7). The mark itself is hidden from a screen reader, so
 * nothing is read twice.
 */
export function CatalogUnitPhoto({
  alt,
  className,
  eager = false,
  locale,
  photo,
  sizes,
}: {
  alt: string;
  className?: string;
  /** Among the first pictures of the page: loaded with it. */
  eager?: boolean;
  locale: string;
  photo: Photo;
  sizes: string;
}) {
  const image = (
    // Our own copies, already sized: nothing for the image optimizer to do.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt={photo.ai_generated ? `${alt}${siteUiTexts(locale).aiImage}` : alt}
      className={className}
      decoding="async"
      loading={eager ? "eager" : "lazy"}
      sizes={sizes}
      src={photo.preview_url}
      srcSet={`${photo.thumbnail_url} 320w, ${photo.preview_url} 1280w`}
      {...(photo.width && photo.height
        ? { width: photo.width, height: photo.height }
        : {})}
    />
  );
  if (!photo.ai_generated) return image;
  return (
    <span className="relative block">
      {image}
      <span
        aria-hidden="true"
        className="absolute top-2 left-2 rounded bg-black/70 px-1.5 py-0.5 text-xs font-semibold text-white"
      >
        AI
      </span>
    </span>
  );
}
