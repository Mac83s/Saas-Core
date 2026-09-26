"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { PencilIcon, PlusIcon } from "lucide-react";

import {
  ApiProblemError,
  createRole,
  deleteRole,
  listMemberships,
  listRoles,
  updateRole,
  type OrganizationSummary,
  type RoleCatalog,
  type RoleSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { managesTeam } from "./role-groups";
import {
  usePermissionLabel,
  useRoleDescription,
  useRoleLabel,
} from "./role-labels";

type Values = { name: string; permissions: string[] };
type Row = RoleSummary & { people: number };

const MEMBERS_READ = "organization.members.read";
const MEMBERS_MANAGE = "organization.members.manage";

/**
 * Zespół › Role i uprawnienia (ADR-057 page, ADR-054 list): the type's system
 * roles, read-only, and the company's own, made from the permissions its
 * modules declare (ADR-050).
 */
export function RolesPanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("Roles");
  const team = useTranslations("TeamPage");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const params = useSearchParams();
  const permissions = new Set(organization?.permissions);
  const canRead = permissions.has(MEMBERS_READ);
  const canManage = permissions.has(MEMBERS_MANAGE);
  const [catalog, setCatalog] = useState<RoleCatalog>();
  const [people, setPeople] = useState<Map<string, number>>(new Map());
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  // "Utwórz rolę" in the role dialog of a person leads here with ?new=1.
  const [editing, setEditing] = useState<RoleSummary | "new" | null>(() =>
    canManage && params?.get("new") ? "new" : null,
  );
  const permissionLabel = usePermissionLabel();
  const roleLabel = useRoleLabel(catalog, organization?.organization_type);
  const describe = useRoleDescription(catalog);
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(2, t("nameRequired")),
        permissions: z.array(z.string()),
      }),
    [t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", permissions: [] },
  });

  const load = useCallback(async () => {
    try {
      const [roles, members] = await Promise.all([
        listRoles(),
        listMemberships(),
      ]);
      // Strongest first — the order a ladder of roles is read in.
      roles.roles.sort((a, b) => b.permissions.length - a.permissions.length);
      const counts = new Map<string, number>();
      for (const member of members)
        counts.set(member.role, (counts.get(member.role) ?? 0) + 1);
      setCatalog(roles);
      setPeople(counts);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (canRead) void load();
  }, [canRead, load]);

  useEffect(() => {
    if (editing === null) return;
    form.reset(
      editing === "new"
        ? { name: "", permissions: [] }
        : { name: editing.name, permissions: [...editing.permissions] },
    );
  }, [editing, form]);

  async function submit(values: Values) {
    setProblem(undefined);
    try {
      if (editing === "new") await createRole(values);
      else if (editing)
        await updateRole(editing.key, { version: editing.version, ...values });
      setEditing(null);
      setNotice(t("saved", { name: values.name }));
      await load();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("failed"),
      );
    }
  }

  async function remove(role: RoleSummary) {
    setProblem(undefined);
    try {
      await deleteRole(role.key);
      setNotice(t("deleted", { name: role.name }));
      await load();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError && error.problem.status === 409
          ? t("inUse")
          : t("failed"),
      );
    }
  }

  const rows: Row[] = (catalog?.roles ?? []).map((role) => ({
    ...role,
    people: people.get(role.key) ?? 0,
  }));
  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "role",
      accessorFn: (role) => roleLabel(role.key),
      header: t("colRole"),
      meta: { primary: true },
      cell: ({ row: { original: role } }) => (
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {roleLabel(role.key)}
          {managesTeam(role) ? (
            <Badge variant="secondary">{t("manages")}</Badge>
          ) : null}
          <Badge variant={role.scope === "system" ? "outline" : "secondary"}>
            {role.scope === "system" ? t("system") : t("own")}
          </Badge>
        </p>
      ),
    },
    {
      id: "access",
      header: t("colAccess"),
      enableSorting: false,
      cell: ({ row: { original: role } }) => (
        <span className="text-muted-foreground">{describe(role)}</span>
      ),
    },
    {
      id: "people",
      accessorKey: "people",
      header: t("colPeople"),
      meta: { className: "tabular-nums" },
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: role } }) =>
        canManage && role.scope === "organization" ? (
          <RowActions
            items={[
              {
                label: t("edit"),
                icon: <PencilIcon aria-hidden="true" />,
                inline: true,
                onSelect: () => {
                  setProblem(undefined);
                  setEditing(role);
                },
              },
              {
                label: t("delete"),
                destructive: true,
                onSelect: () => void remove(role),
              },
            ]}
            label={t("actionsFor", { name: role.name })}
          />
        ) : null,
    },
  ];

  return (
    <PanelPage
      actions={
        canManage ? (
          <Button
            onClick={() => {
              setProblem(undefined);
              setEditing("new");
            }}
          >
            <PlusIcon aria-hidden="true" />
            {t("create")}
          </Button>
        ) : null
      }
      description={t("description")}
      eyebrow={team("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {!canRead ? (
        <p className="text-muted-foreground">{team("noAccess")}</p>
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {team("retry")}
          </Button>
        </div>
      ) : (
        <>
          {problem && editing === null ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={rows}
            getRowId={(role) => role.key}
            labels={labels}
            loading={!catalog}
          />
        </>
      )}
      <Dialog
        onOpenChange={(next) => (next ? undefined : setEditing(null))}
        open={editing !== null && catalog !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {editing === "new" ? t("create") : t("edit")}
            </DialogTitle>
            <DialogDescription>{t("createDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={form.handleSubmit(submit)}>
            <FieldGroup>
              <Field data-invalid={Boolean(form.formState.errors.name)}>
                <FieldLabel htmlFor="role-name">{t("name")}</FieldLabel>
                <Input
                  aria-invalid={Boolean(form.formState.errors.name)}
                  id="role-name"
                  {...form.register("name")}
                />
                <FieldError errors={[form.formState.errors.name]} />
              </Field>
              <FieldSet>
                <FieldLegend>{t("permissions")}</FieldLegend>
                <div className="grid max-h-72 gap-2 overflow-y-auto sm:grid-cols-2">
                  {catalog?.grantable_permissions.map((permission) => (
                    <label
                      className="flex items-center gap-2 text-sm"
                      key={permission}
                    >
                      <input
                        className="size-4"
                        type="checkbox"
                        value={permission}
                        {...form.register("permissions")}
                      />
                      {permissionLabel(permission)}
                    </label>
                  ))}
                </div>
              </FieldSet>
            </FieldGroup>
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>
                {common("cancel")}
              </DialogClose>
              <Button disabled={form.formState.isSubmitting} type="submit">
                {form.formState.isSubmitting ? t("saving") : t("save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
