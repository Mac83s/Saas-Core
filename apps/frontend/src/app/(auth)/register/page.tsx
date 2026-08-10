import Link from "next/link";

import { AuthShell, RegistrationForm } from "../../../modules/core/identity";

export default function RegisterPage() {
  return (
    <AuthShell
      title="Utwórz konto"
      description="Po rejestracji wyślemy wiadomość weryfikacyjną."
      footer={
        <Link className="text-primary hover:underline" href="/verify-email">
          Masz już wiadomość? Potwierdź adres.
        </Link>
      }
    >
      <RegistrationForm />
    </AuthShell>
  );
}
