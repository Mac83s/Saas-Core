"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
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

type Values = { name: string; permissions: string[] };

/** A permission's human label; the raw key when no module translated it. */
export function usePermissionLabel(): (permission: string) => string {
  const t = useTranslations("Permissions");
  return (permission) => {
    const key = permission.replaceAll(".", "_");
    return t.has(key) ? t(key) : permission;
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
}: {
  catalog: RoleCatalog;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Roles");
  const common = useTranslations("Common");
  const permissionLabel = usePermissionLabel();
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
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        {canManage ? (
          <Button onClick={() => open("new")} size="sm" type="button">
            <PlusIcon aria-hidden="true" />
            {t("create")}
          </Button>
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
              <p className="font-medium">{role.name}</p>
              <p className="text-xs text-muted-foreground">
                {t("permissionCount", { count: role.permissions.length })}
              </p>
            </div>
            <Badge variant={role.scope === "system" ? "secondary" : "outline"}>
              {role.scope === "system" ? t("system") : t("own")}
            </Badge>
            {canManage && role.scope === "organization" ? (
              <div className="flex gap-2">
                <Button
                  aria-label={`${t("edit")}: ${role.name}`}
                  onClick={() => open(role)}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                >
                  <PencilIcon aria-hidden="true" />
                </Button>
                <Button
                  aria-label={`${t("delete")}: ${role.name}`}
                  onClick={() => void remove(role)}
                  size="icon-sm"
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
