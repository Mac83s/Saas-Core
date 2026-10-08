import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { routing } from "#i18n/routing";

/** Languages written right to left; the locale registry has none today. */
const RIGHT_TO_LEFT = new Set(["ar", "fa", "he", "ur"]);

type Props = {
  /** The `[locale]` of the product's root layout. */
  locale: string;
  /**
   * The message namespaces the pages' *client* components read — the
   * product's own and any of the core's (`Common`, a guest page's). Only
   * these travel to the browser. Server components read every namespace of
   * the language without listing it here.
   */
  namespaces: readonly string[];
  /** For `<html>`: the product's font variable, a theme class. */
  className?: string;
  children: ReactNode;
};

/**
 * The document of a product's public pages (ADR-080) — what its root layout
 * `src/app/product-site/[locale]/layout.tsx` returns. The pages stand beside
 * `app/[locale]`, not under it, so they do not inherit the panel's document:
 * this one gives them `<html lang dir>`, the request's language for
 * next-intl, and a message provider that hands the browser the named
 * namespaces only — under `app/[locale]` every page carries the language's
 * whole catalogue.
 *
 * Not given, because a public site decides them itself: the stylesheet (the
 * layout imports `@saas-core/ui/globals.css` if it wants the core's Tailwind
 * and tokens), the font (a `next/font` variable named `--font-geist` in
 * `className` feeds the core's `font-sans`), the dark-mode script (the
 * panel's `COLOR_SCHEME_SCRIPT`, as the first child, if the site has a dark
 * look at all).
 */
export async function SiteDocument({
  locale,
  namespaces,
  className,
  children,
}: Readonly<Props>) {
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const every = await getMessages();
  const messages = Object.fromEntries(
    namespaces
      .filter((namespace) => namespace in every)
      .map((namespace) => [namespace, every[namespace]]),
  );
  return (
    <html
      lang={locale}
      dir={RIGHT_TO_LEFT.has(locale) ? "rtl" : "ltr"}
      className={className}
    >
      <body>
        <NextIntlClientProvider messages={messages}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}

/** `generateStaticParams` of the product's root layout: every routed language. */
export function siteStaticParams(): { locale: string }[] {
  return routing.locales.map((locale) => ({ locale }));
}
