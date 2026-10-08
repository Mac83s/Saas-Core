import NextLink from "next/link";
import { useLocale } from "next-intl";
import type { ComponentProps } from "react";

import type { SiteParams } from "#lib/product-site/table";
import { siteHref } from "#lib/product-site/site";

type Props = Omit<ComponentProps<typeof NextLink>, "href"> & {
  /** A key of the product's table: `/breeds/[slug]`. */
  route: string;
  params?: SiteParams;
  /** Another language than the reader's — a language switch. */
  locale?: string;
};

/**
 * A link to one of the product's public pages (ADR-080), in the reader's
 * language unless told otherwise. The address comes from the table, so a
 * link cannot point where the router does not answer. Works in server and
 * client components alike.
 */
export function SiteLink({ route, params, locale, ...rest }: Props) {
  const current = useLocale();
  return (
    <NextLink
      href={siteHref(route, locale ?? current, params)}
      hrefLang={locale}
      {...rest}
    />
  );
}
