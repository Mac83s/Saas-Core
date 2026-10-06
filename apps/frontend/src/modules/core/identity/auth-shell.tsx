import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ShieldCheckIcon } from "lucide-react";

import { Link } from "#i18n/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { cn } from "@saas-core/ui/lib/utils";
import { deployment } from "../../../generated/deployment";

/**
 * The frame of every screen before the panel: sign-in, registration, e-mail
 * confirmation, password reset, an invitation and the first run. Its name is
 * the profile's (`product.name`), as on the marketing pages and in the browser
 * tab; the side panel's words are `Identity.hero*`, which a product replaces
 * from its slot (`product.messages`) like any other text (ADR-049).
 */
export function AuthShell({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const t = useTranslations("Identity");
  const { name, platformDomain } = deployment.product;
  // Said only by a build whose own address is this machine's: a public test
  // address is not a local environment, and the note is never the brand line.
  const local = /(^|\.)localhost$/.test(platformDomain);
  const brand = (className?: string) => (
    <Link
      className={cn("flex items-center gap-2 text-sm font-semibold", className)}
      href="/"
    >
      <ShieldCheckIcon aria-hidden="true" className="size-5" />
      {name}
    </Link>
  );
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(20rem,0.8fr)_1.2fr]">
      <section className="bg-primary text-primary-foreground hidden flex-col p-10 lg:flex">
        {brand()}
        <div className="my-auto max-w-md space-y-4">
          <p className="text-sm font-medium opacity-80">{t("heroEyebrow")}</p>
          <h1 className="text-4xl font-semibold tracking-tight">
            {t("heroTitle")}
          </h1>
          <p className="text-sm leading-6 opacity-80">{t("heroDescription")}</p>
        </div>
        {local && (
          <p className="text-xs opacity-70">
            {name} · {t("localEnvironment")}
          </p>
        )}
      </section>
      <section className="flex flex-col items-center justify-center gap-6 px-5 py-12 sm:px-8">
        {/* A phone has no side panel, so the name stands above the card. */}
        {brand("lg:hidden")}
        <Card className="w-full max-w-md shadow-sm">
          <CardHeader>
            <CardTitle className="text-xl">{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent>{children}</CardContent>
          {footer && <div className="border-t px-4 pt-4 text-sm">{footer}</div>}
        </Card>
      </section>
    </main>
  );
}
