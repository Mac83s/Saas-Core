import { getTranslations } from "next-intl/server";

import { AuthShell, VerificationForm } from "../../../../modules/core/identity";

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const [{ token }, t] = await Promise.all([
    searchParams,
    getTranslations("Identity"),
  ]);
  // With a token this is the confirmation itself; without one it is the screen
  // an account waits on between signing up and the message arriving.
  return (
    <AuthShell
      title={t(token ? "verifyTitle" : "pendingTitle")}
      description={t(token ? "verifyDescription" : "pendingDescription")}
    >
      <VerificationForm token={token} />
    </AuthShell>
  );
}
