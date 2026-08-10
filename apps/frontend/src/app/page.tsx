import { HealthPanel } from "#components/health-panel";
import { deployment } from "../generated/deployment";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center px-6 py-16">
      <section className="flex w-full flex-col gap-8">
        <div className="flex flex-col gap-3">
          <p className="text-primary text-sm font-medium">
            {deployment.product.name} / W2
          </p>
          <h1 className="text-4xl font-semibold tracking-tight">
            Lokalny runtime platformy działa
          </h1>
          <p className="text-muted-foreground max-w-2xl text-lg">
            Caddy kieruje panel i API w modelu same-origin, a frontend nadal
            korzysta ze wspólnego systemu shadcn/ui i generowanego klienta API.
          </p>
        </div>
        <HealthPanel />
      </section>
    </main>
  );
}
