"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  updateMembership,
  type MembershipSummary,
  type RoleCatalog,
  type RoleSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { Link } from "#i18n/navigation";
import { assignableRoles } from "./role-groups";
import { useRoleDescription, useRoleLabel } from "./role-labels";

/**
 * "Zmień rolę": the roles in two groups, management first, each with what it
 * opens — how a trimmer is added to the office (plan: phase 2). The change
 * works from the person's next click; nobody is signed out (ADR-058 §9).
 */
export function ChangeRoleDialog({
  member,
  name,
  catalog,
  canManage,
  canCreateRole,
  organizationType,
  onChanged,
  onOpenChange,
  finalFocus,
}: {
  member: MembershipSummary | undefined;
  name: string;
  catalog: RoleCatalog;
  /** organization.members.manage: every role, not only the type's limited. */
  canManage: boolean;
  /** Offers "Utwórz rolę" for a set of permissions no role has. */
  canCreateRole: boolean;
  organizationType?: string;
  onChanged: (role: string) => void;
  onOpenChange: (open: boolean) => void;
  finalFocus?: HTMLElement | null;
}) {
  const t = useTranslations("People");
  const common = useTranslations("Common");
  const roleLabel = useRoleLabel(catalog, organizationType);
  const describe = useRoleDescription(catalog);
  const [chosen, setChosen] = useState(member?.role ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const groups = assignableRoles(catalog.roles, canManage);

  async function submit() {
    if (!member) return;
    setBusy(true);
    setProblem(undefined);
    try {
      await updateMembership(member.id, { role: chosen });
      onChanged(chosen);
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError && error.problem.status === 403
          ? t("forbidden")
          : t("failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  const option = (role: RoleSummary) => (
    <label
      className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-checked:border-primary has-checked:bg-primary/5"
      key={role.key}
    >
      <input
        checked={chosen === role.key}
        className="mt-1 size-4 accent-primary"
        name="member-role"
        onChange={() => setChosen(role.key)}
        type="radio"
        value={role.key}
      />
      <span className="min-w-0 flex-1 space-y-0.5">
        <span className="flex flex-wrap items-center gap-2 font-medium">
          {roleLabel(role.key)}
          {role.scope === "organization" ? (
            <Badge variant="outline">{t("roleOwn")}</Badge>
          ) : null}
          {member?.role === role.key ? (
            <Badge variant="secondary">{t("roleCurrent")}</Badge>
          ) : null}
        </span>
        <span className="block text-sm text-muted-foreground">
          {describe(role)}
        </span>
      </span>
    </label>
  );

  return (
    <Dialog onOpenChange={onOpenChange} open={member !== undefined}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("changeRoleTitle", { name })}</DialogTitle>
            <DialogDescription>{t("changeRoleDescription")}</DialogDescription>
          </DialogHeader>
          {(
            [
              ["management", groups.management],
              ["work", groups.work],
            ] as const
          ).map(([group, roles]) =>
            roles.length ? (
              <fieldset className="space-y-2" key={group}>
                <legend className="mb-2 text-sm font-semibold">
                  {t(group === "management" ? "groupManagement" : "groupWork")}
                </legend>
                {roles.map(option)}
              </fieldset>
            ) : null,
          )}
          <p className="text-sm text-muted-foreground">{t("roleNote")}</p>
          {canCreateRole ? (
            <p className="text-sm text-muted-foreground">
              {t("roleOther")}{" "}
              <Link
                className="font-medium text-primary hover:underline"
                href="/panel/team/roles?new=1"
              >
                {t("roleCreate")}
              </Link>
            </p>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy || !chosen || chosen === member?.role}
              type="submit"
            >
              {t("changeRoleSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
