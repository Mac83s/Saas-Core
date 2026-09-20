import { getLocale, getTranslations } from "next-intl/server";

import { LocaleSwitcher } from "#components/locale-switcher";
import { Link } from "#i18n/navigation";
import { Button } from "@saas-core/ui/components/button";

import { productCopy, productName } from "../content";

export async function SiteHeader() {
  const t = await getTranslations("Marketing");
  const copy = productCopy(await getLocale());
  const links = [
    ...(copy.pages?.length
      ? copy.pages.map((page) => ({
          href: `/${page.slug}`,
          label: page.navLabel,
        }))
      : [{ href: "/#features", label: t("nav.features") }]),
    { href: "/pricing", label: t("nav.pricing") },
    { href: "/contact", label: t("nav.contact") },
  ];

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-5">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          {productName}
        </Link>
        <nav
          aria-label={t("nav.label")}
          className="hidden items-center gap-6 md:flex"
        >
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div className="hidden sm:block">
            <LocaleSwitcher />
          </div>
          <Button render={<Link href="/login" />} variant="ghost" size="sm">
            {t("signIn")}
          </Button>
          <Button render={<Link href="/register" />} size="sm">
            {t("signUp")}
          </Button>
        </div>
      </div>
      {/* Native disclosure: a menu that works before any script has loaded. */}
      <details className="border-t md:hidden">
        <summary className="cursor-pointer px-5 py-3 text-sm font-medium">
          {t("nav.menu")}
        </summary>
        <nav
          aria-label={t("nav.label")}
          className="flex flex-col gap-1 px-5 pb-4"
        >
          {links.map((link) => (
            <Link key={link.href} href={link.href} className="py-2 text-sm">
              {link.label}
            </Link>
          ))}
          <div className="pt-2">
            <LocaleSwitcher />
          </div>
        </nav>
      </details>
    </header>
  );
}
