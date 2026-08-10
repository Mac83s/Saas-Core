import { getTranslations } from "next-intl/server";
import { ArrowRightIcon, ShieldCheckIcon } from "lucide-react";

import { HealthPanel } from "#components/health-panel";
import { Link } from "#i18n/navigation";
import { deployment } from "../../generated/deployment";
import { Button } from "@saas-core/ui/components/button";

export default async function HomePage() {
  const t = await getTranslations("Home");
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center px-6 py-16">
      <section className="flex w-full flex-col gap-8">
        <div className="flex flex-col gap-3">
          <p className="text-sm font-medium text-primary">
            {deployment.product.name} / {t("stage")}
          </p>
          <h1 className="text-4xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="max-w-2xl text-lg text-muted-foreground">
            {t("description")}
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Button render={<Link href="/panel" />} size="lg">
              <ShieldCheckIcon aria-hidden="true" />
              {t("openPanel")}
            </Button>
            <Button
              render={<Link href="/register" />}
              size="lg"
              variant="outline"
            >
              {t("createAccount")}
              <ArrowRightIcon aria-hidden="true" />
            </Button>
          </div>
        </div>
        <HealthPanel />
      </section>
    </main>
  );
}
