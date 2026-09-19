"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";

import {
  ApiProblemError,
  createRole,
  deleteRole,
  updateRole,
  type RoleCatalog,
  type RoleSummary,
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

import { typeRole, typeText } from "#lib/organization-types";
import { roleAccess } from "./role-access";

type Values = { name: string; permissions: string[] };

const GLOBAL_ROLES = new Set(["owner", "admin", "manager", "staff", "viewer"]);

/** A permission's human label; the raw key when no module translated it. */
export function usePermissionLabel(): (permission: string) => string {
  const t = useTranslations("Permissions");
  return (permission) => {
    const key = permission.replaceAll(".", "_");
    return t.has(key) ? t(key) : permission;
  };
}

/**
 * A role's name: the label its organization type gives it (ADR-050), core's
 * translation of a global role, or the name the organization chose.
 */
export function useRoleLabel(
  catalog: RoleCatalog | undefined,
  organizationType?: string,
): (key: string) => string {
  const t = useTranslations("Organizations");
  const locale = useLocale();
  return (key) => {
    const typed = typeRole(organizationType, key);
    if (typed) return typeText(typed.label, locale);
    if (GLOBAL_ROLES.has(key)) return t(key);
    return catalog?.roles.find((role) => role.key === key)?.name ?? key;
  };
}

/** One sentence on what a role may do, from its permissions (role-access). */
export function useRoleDescription(
  catalog: RoleCatalog | undefined,
): (role: RoleSummary) => string {
  const t = useTranslations("Roles");
  const permissionLabel = usePermissionLabel();
  const offered = catalog?.roles.flatMap((role) => role.permissions) ?? [];
  const areas = (keys: string[]) =>
    keys.map((key) => t(`area_${key}`)).join(", ");
  return (role) => {
    const access = roleAccess(role.permissions, offered);
    if (access.kind !== "list")
      return access.kind === "except"
        ? t("accessExcept", { areas: areas(access.areas) })
        : t(access.kind === "full" ? "accessFull" : "accessBasic");
    return [
      access.edit.length ? t("accessEdit", { areas: areas(access.edit) }) : "",
      access.view.length ? t("accessView", { areas: areas(access.view) }) : "",
      access.also.length
        ? t("accessAlso", {
            items: access.also.map(permissionLabel).join(", "),
          })
        : "",
      access.none.length ? t("accessNone", { areas: areas(access.none) }) : "",
    ]
      .filter(Boolean)
      .join(" ");
  };
}

/**
 * The roles an organization can hand out (ADR-050): its type's system roles,
 * read-only, and its own, which it creates from the permissions its modules
 * declare.
 */
export function RolesCard({
  catalog,
  canManage,
  onChanged,
  organizationType,
}: {
  catalog: RoleCatalog;
  canManage: boolean;
  onChanged: () => Promise<void>;
  organizationType?: string;
}) {
  const t = useTranslations("Roles");
  const common = useTranslations("Common");
  const permissionLabel = usePermissionLabel();
  const roleLabel = useRoleLabel(catalog, organizationType);
  const describe = useRoleDescription(catalog);
  const [editing, setEditing] = useState<RoleSummary | "new" | null>(null);
  const [problem, setProblem] = useState<string>();
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

  function open(role: RoleSummary | "new") {
    setProblem(undefined);
    form.reset(
      role === "new"
        ? { name: "", permissions: [] }
        : { name: role.name, permissions: [...role.permissions] },
    );
    setEditing(role);
  }

  async function submit(values: Values) {
    setProblem(undefined);
    try {
      if (editing === "new") {
        await createRole(values);
      } else if (editing) {
        await updateRole(editing.key, { version: editing.version, ...values });
      }
      setEditing(null);
      await onChanged();
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
      await onChanged();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError && error.problem.status === 409
          ? t("inUse")
          : t("failed"),
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        {canManage ? (
          <CardAction>
            <Button onClick={() => open("new")} type="button" variant="outline">
              <PlusIcon aria-hidden="true" />
              {t("create")}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {problem && !editing ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        {catalog.roles.map((role) => (
          <div
            className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center"
            key={role.key}
          >
            <div className="min-w-0 flex-1">
              <p className="font-medium">{roleLabel(role.key)}</p>
              <p className="text-muted-foreground">{describe(role)}</p>
            </div>
            <Badge variant={role.scope === "system" ? "secondary" : "outline"}>
              {role.scope === "system" ? t("system") : t("own")}
            </Badge>
            {canManage && role.scope === "organization" ? (
              <div className="flex gap-2">
                <Button
                  aria-label={`${t("edit")}: ${role.name}`}
                  onClick={() => open(role)}
                  size="icon"
                  type="button"
                  variant="ghost"
                >
                  <PencilIcon aria-hidden="true" />
                </Button>
                <Button
                  aria-label={`${t("delete")}: ${role.name}`}
                  onClick={() => void remove(role)}
                  size="icon"
                  type="button"
                  variant="ghost"
                >
                  <Trash2Icon aria-hidden="true" />
                </Button>
              </div>
            ) : null}
          </div>
        ))}
      </CardContent>
      <Dialog
        onOpenChange={(next) => (next ? undefined : setEditing(null))}
        open={editing !== null}
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
                  {catalog.grantable_permissions.map((permission) => (
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
    </Card>
  );
}
