"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useRouter } from "#i18n/navigation";
import {
  selectActiveOrganization,
  type OrganizationSummary,
} from "@saas-core/api-client";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { useSidebar } from "@saas-core/ui/components/sidebar";

export function OrganizationSwitcher({
  organizations,
}: {
  organizations: OrganizationSummary[];
}) {
  const t = useTranslations("Organizations");
  const router = useRouter();
  const { closeMobile } = useSidebar();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState(false);
  const active = organizations.find((organization) => organization.active);

  if (organizations.length === 0) return null;

  async function changeOrganization(organizationId: string) {
    if (!organizationId || organizationId === active?.id || pending) return;
    setPending(true);
    setProblem(false);
    try {
      await selectActiveOrganization(organizationId);
      closeMobile();
      router.refresh();
    } catch {
      setProblem(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-1.5 group-data-[collapsed=true]/sidebar-wrapper:hidden">
      <label
        className="text-xs font-medium text-muted-foreground"
        htmlFor="dashboard-organization-switcher"
      >
        {t("choose")}
      </label>
      <NativeSelect
        aria-invalid={problem || undefined}
        disabled={pending || organizations.length < 2}
        id="dashboard-organization-switcher"
        onChange={(event) => void changeOrganization(event.target.value)}
        value={active?.id ?? ""}
      >
        {organizations.map((organization) => (
          <option key={organization.id} value={organization.id}>
            {organization.name}
          </option>
        ))}
      </NativeSelect>
      {problem ? (
        <p className="text-xs text-destructive" role="alert">
          {t("problem")}
        </p>
      ) : null}
    </div>
  );
}
