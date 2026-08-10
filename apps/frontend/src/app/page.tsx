import Link from "next/link";
import { ArrowRightIcon, ShieldCheckIcon } from "lucide-react";

import { HealthPanel } from "#components/health-panel";
import { deployment } from "../generated/deployment";
import { Button } from "@saas-core/ui/components/button";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center px-6 py-16">
      <section className="flex w-full flex-col gap-8">
        <div className="flex flex-col gap-3">
          <p className="text-primary text-sm font-medium">
            {deployment.product.name} / W3
          </p>
          <h1 className="text-4xl font-semibold tracking-tight">
            Bezpieczny fundament Twojego produktu SaaS
          </h1>
          <p className="text-muted-foreground max-w-2xl text-lg">
            Konto, sesje urządzeń, reset hasła i MFA działają w modelu
            same-origin — bez tokenów uwierzytelniających w localStorage.
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Button render={<Link href="/login" />} size="lg">
              <ShieldCheckIcon aria-hidden="true" />
              Otwórz panel
            </Button>
            <Button
              render={<Link href="/register" />}
              size="lg"
              variant="outline"
            >
              Utwórz konto
              <ArrowRightIcon aria-hidden="true" />
            </Button>
          </div>
        </div>
        <HealthPanel />
      </section>
    </main>
  );
}
