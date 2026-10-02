import { getLocale, getTranslations } from "next-intl/server";

import { LocaleSwitcher } from "#components/locale-switcher";
import { getPathname, Link } from "#i18n/navigation";
import { Button } from "@saas-core/ui/components/button";

import { productCopy, productHasCatalog, productName } from "../content";
import {
  inlineNavFrom,
  type MarketingLink,
  marketingLinks,
} from "../navigation";
import { MobileMenu } from "./mobile-menu";

/** Full literal classes, so Tailwind generates both breakpoints. */
const INLINE_NAV = {
  lg: { nav: "hidden items-center gap-6 lg:flex", menu: "border-t lg:hidden" },
  xl: { nav: "hidden items-center gap-6 xl:flex", menu: "border-t xl:hidden" },
} as const;

export function MarketingNavLink({
  link,
  locale,
  className,
}: {
  link: MarketingLink;
  locale: string;
  className: string;
}) {
  return link.document ? (
    <a href={getPathname({ href: link.href, locale })} className={className}>
      {link.label}
    </a>
  ) : (
    <Link href={link.href} className={className}>
      {link.label}
    </Link>
  );
}

export async function SiteHeader() {
  const t = await getTranslations("Marketing");
  const locale = await getLocale();
  const copy = productCopy(locale);
  const links = marketingLinks(
    copy,
    {
      features: t("nav.features"),
      catalog: t("nav.catalog"),
      pricing: t("nav.pricing"),
      contact: t("nav.contact"),
    },
    { catalog: productHasCatalog },
  );
  const inline = inlineNavFrom(links);
  const layout = INLINE_NAV[inline];

  return (
    <header
      data-marketing-header={inline}
      className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur"
    >
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-5">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          {productName}
        </Link>
        <nav aria-label={t("nav.label")} className={layout.nav}>
          {links.map((link) => (
            <MarketingNavLink
              key={link.href}
              link={link}
              locale={locale}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            />
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
      <MobileMenu label={t("nav.menu")} className={layout.menu}>
        <nav
          aria-label={t("nav.label")}
          className="flex flex-col gap-1 px-5 pb-4"
        >
          {links.map((link) => (
            <MarketingNavLink
              key={link.href}
              link={link}
              locale={locale}
              className="py-2 text-sm"
            />
          ))}
          <div className="pt-2">
            <LocaleSwitcher />
          </div>
        </nav>
      </MobileMenu>
    </header>
  );
}
