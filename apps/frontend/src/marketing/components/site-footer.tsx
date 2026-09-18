import { getLocale, getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";

import { productCopy, productName } from "../content";

export async function SiteFooter() {
  const t = await getTranslations("Marketing");
  const copy = productCopy(await getLocale());

  return (
    <footer className="border-t">
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-5 py-12 sm:grid-cols-3">
        <div className="flex flex-col gap-2">
          <p className="font-semibold">{productName}</p>
          <p className="text-sm text-muted-foreground">{copy.footer.tagline}</p>
        </div>
        <nav aria-label={t("footer.product")} className="flex flex-col gap-2 text-sm">
          <p className="font-medium">{t("footer.product")}</p>
          <Link href="/#features" className="text-muted-foreground hover:text-foreground">
            {t("nav.features")}
          </Link>
          <Link href="/pricing" className="text-muted-foreground hover:text-foreground">
            {t("nav.pricing")}
          </Link>
          <Link href="/contact" className="text-muted-foreground hover:text-foreground">
            {t("nav.contact")}
          </Link>
        </nav>
        <nav aria-label={t("footer.account")} className="flex flex-col gap-2 text-sm">
          <p className="font-medium">{t("footer.account")}</p>
          <Link href="/login" className="text-muted-foreground hover:text-foreground">
            {t("signIn")}
          </Link>
          <Link href="/register" className="text-muted-foreground hover:text-foreground">
            {t("signUp")}
          </Link>
        </nav>
      </div>
      <div className="border-t">
        <p className="mx-auto w-full max-w-6xl px-5 py-6 text-xs text-muted-foreground">
          © {new Date().getFullYear()} {productName}. {t("footer.rights")}
        </p>
      </div>
    </footer>
  );
}
