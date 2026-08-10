import {
  AuthShell,
  PasswordResetConfirmForm,
} from "../../../modules/core/identity";

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <AuthShell
      title="Ustaw nowe hasło"
      description="Po zmianie hasła wszystkie wcześniejsze sesje zostaną unieważnione."
    >
      <PasswordResetConfirmForm token={token} />
    </AuthShell>
  );
}
