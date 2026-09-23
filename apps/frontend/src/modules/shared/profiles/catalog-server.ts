import "server-only";

import type { CatalogProfile } from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * The public card page renders on the server, where the api-client's
 * same-origin relative URL cannot be fetched — Node's fetch needs an absolute
 * one, and every card page answered 500 until this read went to the backend
 * directly. `null` is a withdrawn or erased company: gone, not broken.
 */
export async function readCatalogProfileOnServer(
  city: string,
  slug: string,
): Promise<CatalogProfile | null> {
  const response = await fetch(
    `${backendUrl}/api/v1/public/catalog/${encodeURIComponent(city)}/${encodeURIComponent(slug)}/`,
    { cache: "no-store" },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Public catalog API answered ${response.status}`);
  }
  return (await response.json()) as CatalogProfile;
}
