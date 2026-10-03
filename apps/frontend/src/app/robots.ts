import type { MetadataRoute } from "next";

import { routing } from "#i18n/routing";
import { localizedPath, localizedUrl } from "../marketing/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Every language prefix (TL17): a guest language in front of the panel
      // is a redirect, but a crawler need not follow it to learn that.
      disallow: [
        ...routing.locales.flatMap((locale) =>
          ["/panel", "/settings"].map((path) => localizedPath(locale, path)),
        ),
        "/api/",
      ],
    },
    sitemap: localizedUrl("pl", "/sitemap.xml"),
  };
}
