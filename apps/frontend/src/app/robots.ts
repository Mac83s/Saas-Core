import type { MetadataRoute } from "next";

import { localizedUrl } from "../marketing/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/panel", "/en/panel", "/settings", "/en/settings", "/api/"] },
    sitemap: localizedUrl("pl", "/sitemap.xml"),
  };
}
