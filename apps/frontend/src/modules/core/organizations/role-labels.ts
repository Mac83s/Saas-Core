"use client";

import { useLocale, useTranslations } from "next-intl";

import type { RoleCatalog, RoleSummary } from "@saas-core/api-client";

import { typeRole, typeText } from "#lib/organization-types";
import { roleAccess } from "./role-access";

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
