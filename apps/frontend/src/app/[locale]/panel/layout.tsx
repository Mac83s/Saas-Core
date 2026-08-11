import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { ShieldCheckIcon } from "lucide-react";

import { LocaleSwitcher } from "#components/locale-switcher";
import { Link } from "#i18n/navigation";
import { getServerUser } from "#lib/server-auth";
import { LogoutButton } from "../../../modules/core/identity";

export default async function PanelLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const [{ locale }, user, billing, sites] = await Promise.all([
    params,
    getServerUser(),
    getTranslations("BillingSupport"),
    getTranslations("Sites"),
  ]);
  if (!user) redirect(locale === "pl" ? "/login" : `/${locale}/login`);
  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-5">
          <Link className="flex items-center gap-2 font-semibold" href="/panel">
            <ShieldCheckIcon
              aria-hidden="true"
              className="size-5 text-primary"
            />
            SaaS Core
          </Link>
          <Link
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            href="/panel/sites"
          >
            {sites("navigation")}
          </Link>
          <Link
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            href="/panel/support/billing"
          >
            {billing("navigation")}
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {user.email}
            </span>
            <LocaleSwitcher />
            <LogoutButton />
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
