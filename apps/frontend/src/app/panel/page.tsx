import { getServerUser } from "#lib/server-auth";
import { SessionManager } from "../../modules/core/identity";

export default async function PanelPage() {
  const user = await getServerUser();
  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-5 py-10">
      <section className="space-y-2">
        <p className="text-sm font-medium text-primary">Panel konta</p>
        <h1 className="text-3xl font-semibold tracking-tight">Dzień dobry</h1>
        <p className="text-muted-foreground">
          Zalogowano jako {user?.email}. Tutaj możesz kontrolować aktywne
          urządzenia.
        </p>
      </section>
      <div className="max-w-3xl">
        <SessionManager />
      </div>
    </main>
  );
}
