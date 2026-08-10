"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Link } from "#i18n/navigation";
import { acceptInvitation } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";

import { organizationErrorMessage } from "./problem";

export function InvitationAcceptance({ token }: { token?: string }) {
  const t = useTranslations("InvitationAcceptance");
  const organizations = useTranslations("Organizations");
  const [pending, setPending] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [problem, setProblem] = useState<string>();

  if (!token) {
    return <Problem message={t("missingToken")} />;
  }
  if (accepted) {
    return (
      <div className="space-y-4">
        <div
          className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm"
          role="status"
        >
          {t("accepted")}
        </div>
        <Button className="w-full" render={<Link href="/panel" />}>
          {t("goToPanel")}
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setProblem(undefined);
          try {
            await acceptInvitation(token);
            setAccepted(true);
          } catch (error) {
            setProblem(
              organizationErrorMessage(error, organizations("problem")),
            );
          } finally {
            setPending(false);
          }
        }}
      >
        {pending ? t("accepting") : t("accept")}
      </Button>
    </div>
  );
}

function Problem({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
      role="alert"
    >
      {message}
    </div>
  );
}
