import Link from "next/link";

import {
  AuthShell,
  PasswordResetRequestForm,
} from "../../../modules/core/identity";

export default function PasswordResetPage() {
  return (
    <AuthShell
      title="Zresetuj hasło"
      description="Odpowiedź nie ujawnia, czy konto istnieje."
      footer={
        <Link className="text-primary hover:underline" href="/login">
          Wróć do logowania
        </Link>
      }
    >
      <PasswordResetRequestForm />
    </AuthShell>
  );
}
