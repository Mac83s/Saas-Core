import type { MetadataRoute } from "next";

import { localizedUrl } from "../marketing/seo";

const PATHS = ["/", "/pricing", "/contact"];

/** The product's marketing pages; customer sites have their own under `/site-renderer`. */
export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({
    url: localizedUrl("pl", path),
    alternates: { languages: { pl: localizedUrl("pl", path), en: localizedUrl("en", path) } },
  }));
}
