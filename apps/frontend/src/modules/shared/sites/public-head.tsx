import type { PublicSitePage } from "@saas-core/api-client";

import { JsonLd } from "#components/json-ld";

/**
 * What a public page says to machines beside its metadata; React hoists the
 * link and the meta into the head.
 *
 * - `rel=describedby`: the site's llms.txt in the page's language (TL19).
 * - `digital-source-type`: on a version with text an AI model wrote, always,
 *   whatever the visible notice does (ADR-071 pkt 17) — IPTC's vocabulary,
 *   the same value the structured data carries as `digitalSourceType`.
 * - The structured data the backend built from the same values as the head
 *   (TL18), printed only through `JsonLd`.
 */
export function PublicSiteHead({ page }: { page: PublicSitePage }) {
  return (
    <>
      {page.describedby ? (
        <link href={page.describedby} rel="describedby" type="text/plain" />
      ) : null}
      {page.machine_text ? (
        <meta
          content={page.machine_text.source_type}
          name="digital-source-type"
        />
      ) : null}
      {page.structured_data ? <JsonLd data={page.structured_data} /> : null}
    </>
  );
}
