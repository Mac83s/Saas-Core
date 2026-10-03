import { serializeJsonLd } from "#lib/seo";

/**
 * One JSON-LD block; the only way a page prints structured data (TL18). The
 * data may carry text a company wrote, so it goes through `serializeJsonLd`.
 */
export function JsonLd({ data }: { data: unknown }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
