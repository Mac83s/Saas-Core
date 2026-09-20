import type { MetadataRoute } from "next";

import { localizedUrl } from "../marketing/seo";
import { productCopy } from "../marketing/content";

const PATHS = ["/", "/pricing", "/contact"];

/** The product's marketing pages; customer sites have their own under `/site-renderer`. */
export default function sitemap(): MetadataRoute.Sitemap {
  const paths = [
    ...PATHS,
    ...(productCopy("pl").pages ?? []).map((page) => `/${page.slug}`),
  ];
  return paths.flatMap((path) =>
    (["pl", "en"] as const).map((locale) => ({
      url: localizedUrl(locale, path),
      alternates: {
        languages: {
          pl: localizedUrl("pl", path),
          en: localizedUrl("en", path),
          "x-default": localizedUrl("pl", path),
        },
      },
    })),
  );
}
