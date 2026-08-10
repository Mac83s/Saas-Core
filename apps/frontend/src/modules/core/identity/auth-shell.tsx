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
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(20rem,0.8fr)_1.2fr]">
      <section className="bg-primary text-primary-foreground hidden flex-col justify-between p-10 lg:flex">
        <Link
          className="flex items-center gap-2 text-sm font-semibold"
          href="/"
        >
          <ShieldCheckIcon aria-hidden="true" className="size-5" />
          SaaS Core
        </Link>
        <div className="max-w-md space-y-4">
          <p className="text-sm font-medium opacity-80">{t("securePanel")}</p>
          <h1 className="text-4xl font-semibold tracking-tight">
            {t("heroTitle")}
          </h1>
          <p className="text-sm leading-6 opacity-80">{t("heroDescription")}</p>
        </div>
        <p className="text-xs opacity-70">
          SaaS Core · {t("localEnvironment")}
        </p>
      </section>
      <section className="flex items-center justify-center px-5 py-12 sm:px-8">
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
