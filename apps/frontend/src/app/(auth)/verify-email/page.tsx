import { AuthShell, VerificationForm } from "../../../modules/core/identity";

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <AuthShell
      title="Potwierdź adres e-mail"
      description="Wklej token z wiadomości lub poproś o nową wiadomość."
    >
      <VerificationForm token={token} />
    </AuthShell>
  );
}
