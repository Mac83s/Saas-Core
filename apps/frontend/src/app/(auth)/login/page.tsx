import { redirect } from "next/navigation";

import { getServerUser } from "#lib/server-auth";
import { AuthShell, LoginForm } from "../../../modules/core/identity";

export default async function LoginPage() {
  if (await getServerUser()) redirect("/panel");
  return (
    <AuthShell title="Zaloguj się" description="Użyj konta panelu SaaS Core.">
      <LoginForm />
    </AuthShell>
  );
}
