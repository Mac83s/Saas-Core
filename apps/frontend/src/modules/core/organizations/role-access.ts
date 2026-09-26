/**
 * What a role opens, in the few areas a person thinks in ("edits the
 * calendar, views the farms, no access to billing"). Derived from the role's
 * permissions, so the roles a product declares for its organization types —
 * and roles an organization makes itself — are described without core
 * knowing them.
 */
export type RoleAccess =
  | { kind: "full" }
  | { kind: "basic" }
  | { kind: "except"; areas: string[] }
  | {
      kind: "list";
      edit: string[];
      view: string[];
      /** Permissions of a product's own modules, described by their labels. */
      also: string[];
      none: string[];
    };

// Every role has these; they say nothing about it.
const BASELINE = new Set(["organization.read", "notifications.preferences"]);

// A right to one's own things, not to an area: "own hours" edits nobody's
// visits, so it is named, not counted as editing the calendar.
const OWN = new Set(["booking.schedule.own"]);

// Core's and shared modules' permissions by area, in the order they are read.
const AREAS: readonly (readonly [prefix: string, area: string])[] = [
  ["booking.", "bookings"],
  ["farms.", "farms"],
  ["site.", "website"],
  ["profiles.", "website"],
  ["seo.", "website"],
  ["notifications.", "messages"],
  ["media.", "files"],
  ["organization.members.", "team"],
  ["organization.settings.", "settings"],
  ["integrations.", "integrations"],
  ["organization.billing.", "billing"],
  ["organization.ownership.", "ownership"],
  ["organization.archive", "ownership"],
];
const ORDER = [...new Set(AREAS.map(([, area]) => area))];

// "No access" names only what people ask about: the team and the money.
const PRIVATE = ["team", "settings", "billing"];

function areaOf(permission: string): string | undefined {
  return AREAS.find(([prefix]) => permission.startsWith(prefix))?.[1];
}

/**
 * @param permissions the role's
 * @param offered every permission any role of the organization holds
 */
export function roleAccess(
  permissions: readonly string[],
  offered: readonly string[],
): RoleAccess {
  const own = new Set(permissions);
  // Own hours is less than managing the calendar: no role is short of "full"
  // for lacking it, but a role that has it says so.
  const meaningful = offered.filter(
    (permission) => !BASELINE.has(permission) && !OWN.has(permission),
  );
  if (meaningful.every((permission) => own.has(permission)))
    return { kind: "full" };

  const edits = new Map<string, boolean>();
  const also = new Map<string, string>();
  for (const permission of own) {
    if (BASELINE.has(permission)) continue;
    const writes = !permission.endsWith(".read");
    const area = OWN.has(permission) ? undefined : areaOf(permission);
    if (area) {
      edits.set(area, (edits.get(area) ?? false) || writes);
      continue;
    }
    // "Manage herds" says more than "View herds": keep the stronger one.
    const group = permission.slice(0, permission.lastIndexOf("."));
    if (writes || !also.has(group)) also.set(group, permission);
  }
  if (edits.size === 0 && also.size === 0) return { kind: "basic" };

  const offeredAreas = new Set(meaningful.map(areaOf));
  const edit = ORDER.filter((area) => edits.get(area) === true);
  const view = ORDER.filter((area) => edits.get(area) === false);
  const missing = ORDER.filter(
    (area) => offeredAreas.has(area) && !edits.has(area),
  );
  const hasAllOfProduct = meaningful
    .filter((permission) => !areaOf(permission))
    .every((permission) => own.has(permission));
  // Nearly everything: naming the few gaps is shorter than listing it all.
  if (view.length === 0 && hasAllOfProduct && missing.length < edit.length)
    return { kind: "except", areas: missing };
  return {
    kind: "list",
    edit,
    view,
    also: [...also.values()],
    none: missing.filter((area) => PRIVATE.includes(area)),
  };
}
