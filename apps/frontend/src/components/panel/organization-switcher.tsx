"use client";

import { useState } from "react";
import { ChevronsUpDownIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRouter } from "#i18n/navigation";
import {
  selectActiveOrganization,
  type OrganizationSummary,
} from "@saas-core/api-client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";
import { useSidebar } from "@saas-core/ui/components/sidebar";

/** The company at the top of the menu: who you work for and as whom. */
export function OrganizationSwitcher({
  organizations,
  roleLabel,
}: {
  organizations: OrganizationSummary[];
  roleLabel: string;
}) {
  const t = useTranslations("Organizations");
  const router = useRouter();
  const { closeMobile } = useSidebar();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState(false);
  const active = organizations.find((organization) => organization.active);

  // After signing in with several memberships none is active yet; the
  // switcher is then the way to pick one, so it must stay.
  if (organizations.length === 0) return null;

  async function changeOrganization(organizationId: string) {
    if (organizationId === active?.id || pending) return;
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
    <div className="min-w-0 flex-1">
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex min-h-13 w-full items-center gap-2.5 rounded-lg border border-foreground/15 bg-background px-2.5 text-left transition-colors hover:bg-foreground/4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-60 group-data-[collapsed=true]/sidebar-wrapper:justify-center group-data-[collapsed=true]/sidebar-wrapper:border-transparent group-data-[collapsed=true]/sidebar-wrapper:px-0"
          disabled={pending}
        >
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground uppercase"
          >
            {active?.name.trim().charAt(0) ?? "?"}
          </span>
          <span className="min-w-0 flex-1 group-data-[collapsed=true]/sidebar-wrapper:sr-only">
            <span className="block truncate text-[0.8125rem] font-semibold">
              {active?.name ?? t("choose")}
            </span>
            {active && roleLabel ? (
              <span className="block truncate text-xs text-muted-foreground">
                {roleLabel}
              </span>
            ) : null}
            {active ? <span className="sr-only">, {t("choose")}</span> : null}
          </span>
          <ChevronsUpDownIcon
            aria-hidden="true"
            className="size-4 shrink-0 opacity-50 group-data-[collapsed=true]/sidebar-wrapper:hidden"
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-(--anchor-width)">
          <DropdownMenuGroup>
            <DropdownMenuLabel>{t("choose")}</DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuRadioGroup
            onValueChange={(value) => void changeOrganization(String(value))}
            value={active?.id ?? null}
          >
            {organizations.map((organization) => (
              <DropdownMenuRadioItem
                key={organization.id}
                value={organization.id}
              >
                <span className="truncate">{organization.name}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      {problem ? (
        <p className="mt-1.5 text-xs text-destructive" role="alert">
          {t("problem")}
        </p>
      ) : null}
    </div>
  );
}
