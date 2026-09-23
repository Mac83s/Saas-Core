"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ComponentProps } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { UserPlusIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createInvitation,
  listInvitations,
  listMemberships,
  listRoles,
  revokeInvitation,
  transferOwnership,
  updateMembership,
  type InvitationSummary,
  type MembershipSummary,
  type OrganizationSummary,
  type RoleCatalog,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  DataTable,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useRouter } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { RolesCard, useRoleDescription, useRoleLabel } from "./roles-card";

// The API decides; these only keep the screen from offering a 403.
const MEMBERS_READ = "organization.members.read";
const MEMBERS_MANAGE = "organization.members.manage";
const MEMBERS_MANAGE_LIMITED = "organization.members.manage_limited";
const OWNERSHIP_TRANSFER = "organization.ownership.transfer";

type Team = {
  members: MembershipSummary[];
  invitations: InvitationSummary[];
  catalog: RoleCatalog;
};
type Pending = {
  kind: "role" | "remove" | "transfer";
  member: MembershipSummary;
};
type Row = {
  key: string;
  name: string;
  email?: string;
  self?: boolean;
  role: string;
  status: string;
  badge: ComponentProps<typeof Badge>["variant"];
  /** Since when a member is in, or until when an invitation holds. */
  note: string;
  items: RowAction[];
};

function memberName(member: MembershipSummary): string {
  return [member.first_name, member.last_name].join(" ").trim() || member.email;
}

/**
 * The team screen: who is in the organization, with which role, who is
 * invited — and the changes the person's permissions allow. Role names come
 * from the organization's type or catalogue, descriptions from each role's
 * permissions, so a product's roles need nothing from core.
 */
export function TeamPanel({
  organization,
  userId,
}: {
  organization: OrganizationSummary | null;
  userId?: string;
}) {
  const t = useTranslations("TeamPage");
  const org = useTranslations("Organizations");
  const common = useTranslations("Common");
  const tableLabels = useDataTableLabels();
  const format = useFormatter();
  const router = useRouter();
  const permissions = new Set(organization?.permissions);
  const canRead = permissions.has(MEMBERS_READ);
  const canManage = permissions.has(MEMBERS_MANAGE);
  const canInvite = canManage || permissions.has(MEMBERS_MANAGE_LIMITED);
  const canTransfer =
    organization?.role === "owner" && permissions.has(OWNERSHIP_TRANSFER);

  const [team, setTeam] = useState<Team>();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [pending, setPending] = useState<Pending>();
  const [pendingOpen, setPendingOpen] = useState(false);
  const [nextRole, setNextRole] = useState("");
  // The row menu that opened a dialog gets focus back when it closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const roleLabel = useRoleLabel(
    team?.catalog,
    organization?.organization_type,
  );
  const describe = useRoleDescription(team?.catalog);

  const inviteSchema = useMemo(
    () => z.object({ email: z.email(org("invalidEmail")), role: z.string() }),
    [org],
  );
  const form = useForm<{ email: string; role: string }>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "" },
  });
  const inviteRole = useWatch({ control: form.control, name: "role" });

  const load = useCallback(async () => {
    try {
      const [members, invitations, catalog] = await Promise.all([
        listMemberships(),
        listInvitations(),
        listRoles(),
      ]);
      // Strongest first — the order a ladder of roles is read in.
      catalog.roles.sort((a, b) => b.permissions.length - a.permissions.length);
      setTeam({ members, invitations, catalog });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (canRead) void load();
  }, [canRead, load]);

  if (!organization || !canRead) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t(organization ? "noAccessTitle" : "noOrganizationTitle")}</h2>
          </CardTitle>
          <CardDescription>
            {t(organization ? "noAccess" : "noOrganization")}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const roles = team?.catalog.roles ?? [];
  const limited = new Set(
    roles.filter((role) => role.limited).map((role) => role.key),
  );
  // Never the owner; without full member management only the type's limited
  // roles (ADR-050) — the same rule the API applies.
  const assignable = roles.filter(
    (role) => role.key !== "owner" && (canManage || role.limited),
  );
  const manages = (role: string) =>
    canInvite && role !== "owner" && (canManage || limited.has(role));
  const members = team?.members ?? [];
  const invitations = (team?.invitations ?? []).filter(
    (invitation) =>
      ["pending", "expired"].includes(invitation.status) &&
      !members.some((member) => member.email === invitation.email),
  );
  const date = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium" });
  const describeKey = (key: string) => {
    const role = roles.find((item) => item.key === key);
    return role ? describe(role) : "";
  };

  // Members and open invitations in one list: status tells them apart.
  const rows: Row[] = [
    ...members.map((member): Row => {
      const name = memberName(member);
      const self = member.user_id === userId;
      const items: RowAction[] = [];
      if (!self && manages(member.role))
        items.push(
          {
            label: t("changeRole"),
            onSelect: (trigger) => ask("role", member, trigger),
          },
          {
            label: t("remove"),
            onSelect: (trigger) => ask("remove", member, trigger),
            destructive: true,
          },
        );
      // Only an active member can take over; never the owner.
      if (
        canTransfer &&
        !self &&
        member.role !== "owner" &&
        member.status === "active"
      )
        items.push({
          label: t("transfer"),
          onSelect: (trigger) => ask("transfer", member, trigger),
          destructive: true,
          separated: items.length > 0,
        });
      const active = member.status === "active";
      return {
        key: member.id,
        name,
        email: name === member.email ? undefined : member.email,
        self,
        role: member.role,
        status: t(active ? "statusActive" : "statusSuspended"),
        badge: active ? "secondary" : "outline",
        note: t("since", { date: date(member.joined_at) }),
        items,
      };
    }),
    ...invitations.map((invitation): Row => {
      const { email, role } = invitation;
      const expired = invitation.status === "expired";
      const items: RowAction[] = [];
      if (manages(role)) {
        if (expired)
          items.push({
            label: t("resend"),
            onSelect: () =>
              void run(
                () => createInvitation({ email, role }),
                t("invited", { email }),
              ),
          });
        items.push({
          label: t("revoke"),
          onSelect: () =>
            void run(
              () => revokeInvitation(invitation.id),
              t("revoked", { email }),
            ),
          destructive: true,
        });
      }
      return {
        key: invitation.id,
        name: email,
        role,
        status: t(expired ? "statusExpired" : "statusInvited"),
        badge: expired ? "destructive" : "outline",
        note: t(expired ? "since" : "expiresOn", {
          date: date(invitation.expires_at),
        }),
        items,
      };
    }),
  ];

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "person",
      accessorKey: "name",
      header: t("person"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {row.name}
            {row.self ? (
              <span className="font-normal text-muted-foreground">
                {" "}
                ({t("you")})
              </span>
            ) : null}
          </p>
          {row.email ? (
            <p className="text-muted-foreground wrap-anywhere">{row.email}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "role",
      header: t("roleAndStatus"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <>
          <p>{roleLabel(row.role)}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground max-md:justify-end">
            <Badge variant={row.badge}>{row.status}</Badge>
            {row.note}
          </p>
        </>
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={row.items}
          label={t("actionsFor", { name: row.name })}
        />
      ),
    },
  ];

  function problemText(error: unknown): string {
    if (!(error instanceof ApiProblemError)) return t("failed");
    if (error.problem.code === "invitation_conflict")
      return t("inviteConflict");
    if (error.problem.status === 403) return t("forbidden");
    return error.message;
  }

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setProblem(undefined);
    setNotice(undefined);
    try {
      await action();
      setNotice(done);
      await load();
      return true;
    } catch (error) {
      setProblem(problemText(error));
      return false;
    } finally {
      setBusy(false);
    }
  }

  function openInvite(open: boolean) {
    setInviteOpen(open);
    setProblem(undefined);
    if (!open) return;
    // Most invitations are for a working role; of the type's limited roles
    // that is the strongest one (the weakest only views).
    const role = assignable.find((item) => item.limited) ?? assignable.at(-1);
    form.reset({ email: "", role: role?.key ?? "" });
  }

  async function invite(values: { email: string; role: string }) {
    const sent = await run(
      () => createInvitation(values),
      t("invited", { email: values.email }),
    );
    if (sent) setInviteOpen(false);
  }

  function ask(
    kind: Pending["kind"],
    member: MembershipSummary,
    trigger: HTMLElement | null,
  ) {
    setReturnTo(trigger);
    setProblem(undefined);
    setNextRole(member.role);
    setPending({ kind, member });
    setPendingOpen(true);
  }

  async function confirm() {
    if (!pending) return;
    const { kind, member } = pending;
    const name = memberName(member);
    if (kind === "transfer") {
      setBusy(true);
      setProblem(undefined);
      try {
        await transferOwnership(member.id);
        // Both people's sessions end with the transfer (the API revokes
        // them), so what follows is signing in again.
        router.replace("/login");
      } catch (error) {
        setProblem(problemText(error));
        setBusy(false);
      }
      return;
    }
    const done =
      kind === "role"
        ? await run(
            () => updateMembership(member.id, { role: nextRole }),
            t("roleChanged", { name }),
          )
        : await run(
            () => updateMembership(member.id, { status: "revoked" }),
            t("removed", { name }),
          );
    if (done) setPendingOpen(false);
  }

  const problemAlert = problem ? (
    <p className="text-sm text-destructive" role="alert">
      {problem}
    </p>
  ) : null;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("membersTitle")}</h2>
          </CardTitle>
          <CardDescription>{t("membersDescription")}</CardDescription>
          {canInvite && assignable.length > 0 ? (
            <CardAction>
              <Dialog onOpenChange={openInvite} open={inviteOpen}>
                <DialogTrigger render={<Button />}>
                  <UserPlusIcon aria-hidden="true" />
                  {org("invite")}
                </DialogTrigger>
                <DialogContent closeLabel={common("close")}>
                  <DialogHeader>
                    <DialogTitle>{org("invite")}</DialogTitle>
                    <DialogDescription>
                      {org("inviteDescription")}
                    </DialogDescription>
                  </DialogHeader>
                  <form
                    className="space-y-4"
                    onSubmit={form.handleSubmit(invite)}
                  >
                    <FieldGroup>
                      <Field
                        data-invalid={Boolean(form.formState.errors.email)}
                      >
                        <FieldLabel htmlFor="invite-email">
                          {org("email")}
                        </FieldLabel>
                        <Input
                          aria-invalid={Boolean(form.formState.errors.email)}
                          autoComplete="off"
                          id="invite-email"
                          type="email"
                          {...form.register("email")}
                        />
                        <FieldError errors={[form.formState.errors.email]} />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="invite-role">
                          {org("role")}
                        </FieldLabel>
                        <NativeSelect
                          aria-describedby="invite-role-access"
                          id="invite-role"
                          {...form.register("role")}
                        >
                          {assignable.map((role) => (
                            <option key={role.key} value={role.key}>
                              {roleLabel(role.key)}
                            </option>
                          ))}
                        </NativeSelect>
                        <FieldDescription id="invite-role-access">
                          {describeKey(inviteRole)}
                        </FieldDescription>
                      </Field>
                    </FieldGroup>
                    {inviteOpen ? problemAlert : null}
                    <DialogFooter>
                      <DialogClose render={<Button variant="outline" />}>
                        {common("cancel")}
                      </DialogClose>
                      <Button disabled={busy} type="submit">
                        {busy ? org("sending") : org("sendInvitation")}
                      </Button>
                    </DialogFooter>
                  </form>
                </DialogContent>
              </Dialog>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {failed ? (
            <div className="flex flex-wrap items-center gap-3" role="alert">
              <p className="text-sm text-destructive">{t("loadError")}</p>
              <Button onClick={() => void load()} variant="outline">
                {t("retry")}
              </Button>
            </div>
          ) : (
            <DataTable
              caption={t("tableCaption")}
              columns={columns}
              data={rows}
              getRowId={(row) => row.key}
              labels={tableLabels}
              loading={!team}
              searchText={(row) =>
                [row.name, row.email, roleLabel(row.role), row.status].join(" ")
              }
              searchable={rows.length > 10}
            />
          )}
          {team && canInvite && members.length <= 1 && !invitations.length ? (
            <p className="text-muted-foreground">{t("alone")}</p>
          ) : null}
          <p aria-live="polite" className="text-sm text-success-foreground">
            {notice}
          </p>
          {inviteOpen || pendingOpen ? null : problemAlert}
        </CardContent>
      </Card>

      {team ? (
        <RolesCard
          canManage={canManage}
          catalog={team.catalog}
          onChanged={load}
          organizationType={organization.organization_type}
        />
      ) : null}

      <Dialog
        onOpenChange={(open) => {
          if (open) return;
          setPendingOpen(false);
          setProblem(undefined);
        }}
        open={pendingOpen}
      >
        <DialogContent
          closeLabel={common("close")}
          finalFocus={() => returnTo ?? true}
        >
          {pending ? (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void confirm();
              }}
            >
              <DialogHeader>
                <DialogTitle>
                  {pending.kind === "role"
                    ? t("changeRoleTitle", { name: memberName(pending.member) })
                    : pending.kind === "remove"
                      ? t("removeTitle", { name: memberName(pending.member) })
                      : t("transferTitle")}
                </DialogTitle>
                <DialogDescription>
                  {pending.kind === "role"
                    ? t("changeRoleDescription")
                    : pending.kind === "remove"
                      ? t("removeDescription")
                      : t("transferDescription", {
                          name: memberName(pending.member),
                          organization: organization.name,
                          owner: roleLabel("owner"),
                          admin: roleLabel("admin"),
                        })}
                </DialogDescription>
              </DialogHeader>
              {pending.kind === "role" ? (
                <Field>
                  <FieldLabel htmlFor="member-role">{t("newRole")}</FieldLabel>
                  <NativeSelect
                    aria-describedby="member-role-access"
                    id="member-role"
                    onChange={(event) => setNextRole(event.target.value)}
                    value={nextRole}
                  >
                    {assignable.map((role) => (
                      <option key={role.key} value={role.key}>
                        {roleLabel(role.key)}
                      </option>
                    ))}
                  </NativeSelect>
                  <FieldDescription id="member-role-access">
                    {describeKey(nextRole)}
                  </FieldDescription>
                </Field>
              ) : null}
              {pending.kind === "transfer" ? (
                <p className="text-sm font-medium">{t("transferSignOut")}</p>
              ) : null}
              {pendingOpen ? problemAlert : null}
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />}>
                  {common("cancel")}
                </DialogClose>
                <Button
                  disabled={
                    busy ||
                    (pending.kind === "role" &&
                      nextRole === pending.member.role)
                  }
                  type="submit"
                  variant={pending.kind === "role" ? "default" : "destructive"}
                >
                  {pending.kind === "role"
                    ? t("changeRole")
                    : pending.kind === "remove"
                      ? t("remove")
                      : t("transferConfirm")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
