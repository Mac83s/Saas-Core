import type { Metadata } from "next";
import type { ReactNode } from "react";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { Geist } from "next/font/google";
import { notFound } from "next/navigation";

import { deployment } from "../../generated/deployment";
import { routing } from "#i18n/routing";
import "@saas-core/ui/globals.css";

// The product is whatever the profile composed, not this repository's name:
// two products build from this tree, and a hardcoded title puts the first one's
// name in the second one's browser tab.
export const metadata: Metadata = {
  title: deployment.product.name,
  description: `${deployment.product.name} — panel`,
};

// Self-hosted at build time; latin-ext carries the Polish diacritics.
const geist = Geist({
  subsets: ["latin", "latin-ext"],
  variable: "--font-geist",
});

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: Readonly<{
  children: ReactNode;
  params: Promise<{ locale: string }>;
}>) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  return (
    <html lang={locale} className={geist.variable} data-color-scheme="auto">
      <body>
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
