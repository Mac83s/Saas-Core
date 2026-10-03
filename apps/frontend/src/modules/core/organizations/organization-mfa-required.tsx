"use client";

import { useTranslations } from "next-intl";

import { Button } from "@saas-core/ui/components/button";

import { TwoFactorCard } from "../identity/account-security";

/**
 * The company requires two-factor sign-in of this account and it has none
 * (owner answer 35a): every company request is refused until it is on, so the
 * panel shows how to turn it on in place of whatever page was asked. Another
 * company stays one switch away in the sidebar.
 */
export function OrganizationMfaRequired({ company }: { company: string }) {
  const t = useTranslations("OrganizationMfa");
  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-2" role="alert">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">
          {company ? t("description", { company }) : t("descriptionNoName")}
        </p>
        <p className="text-sm text-muted-foreground">{t("otherCompany")}</p>
      </div>
      <TwoFactorCard />
      <Button onClick={() => window.location.reload()} variant="outline">
        {t("continue")}
      </Button>
    </div>
  );
}
