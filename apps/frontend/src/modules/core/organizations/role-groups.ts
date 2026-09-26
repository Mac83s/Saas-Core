import type { RoleSummary } from "@saas-core/api-client";

/** What a role lets one run: assigning visits, the team or the company. */
const MANAGEMENT = [
  "booking.appointment.manage",
  "organization.members.manage",
  "organization.members.manage_limited",
  "organization.settings.manage",
];

/**
 * "Zarządzanie" or "Praca", from the role's permissions, so a product's roles
 * and a company's own ones fall into place without code: HoofCare's office in
 * management, its trimmer at work (owner's answer 4 of 24.09).
 */
export function managesTeam(role: Pick<RoleSummary, "permissions">): boolean {
  return MANAGEMENT.some((permission) => role.permissions.includes(permission));
}

/**
 * The roles a person may hand out, management first: never the owner, and
 * without full member management only the type's limited ones (ADR-050) — the
 * rule the API applies.
 */
export function assignableRoles(
  roles: RoleSummary[],
  canManage: boolean,
): { management: RoleSummary[]; work: RoleSummary[] } {
  const offered = roles.filter(
    (role) => role.key !== "owner" && (canManage || role.limited),
  );
  return {
    management: offered.filter(managesTeam),
    work: offered.filter((role) => !managesTeam(role)),
  };
}
