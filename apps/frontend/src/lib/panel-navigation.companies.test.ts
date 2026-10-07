import { describe, expect, it } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

import { deployment } from "../generated/deployment";
import { modulesFor, organizationType, typeRole } from "./organization-types";
import {
  mobileTabs,
  panelAccess,
  panelNavigation,
  sectionTabs,
  type PanelAccess,
} from "./panel-navigation";

/**
 * Nothing is mocked here on purpose: the deployment's own types and the
 * product's own menu (`src/product`). A product takes this file with the core,
 * so the same statement is checked in its composition — the panel of a
 * company is what it was before the platform workspace got a publisher's
 * (ADR-077 pkt 9): the kind of workspace changes nothing unless it is
 * `platform`.
 */
const EVERYTHING = [
  "organization.read",
  "organization.members.read",
  "organization.members.manage",
  "organization.members.manage_limited",
  "organization.settings.manage",
  "organization.billing.manage",
  "booking.appointment.read",
  "booking.appointment.manage",
  "booking.staff.performance.read",
  "commerce.orders.read",
  "customers.read",
  "farms.read",
  "farms.manage",
  "inventory.read",
  "inventory.use",
  "inventory.manage",
  "notifications.manage",
  "integrations.manage",
  "profiles.manage",
  "seo.audit.read",
  "site.content.edit",
  "assistant.use",
];
const PATHS = [
  "/panel",
  "/panel/calendar",
  "/panel/team",
  "/panel/inventory",
  "/panel/sites/blog",
  "/panel/notifications",
  "/panel/settings/billing",
  "/panel/settings/company",
];

/** The access of a membership as the panel computed it before ADR-077 pkt 9. */
function before(organization: OrganizationSummary): PanelAccess {
  const type = organization.organization_type;
  return {
    modules: [...modulesFor(type)],
    permissions: organization.permissions,
    isOwner: organization.role === "owner",
    limited: typeRole(type, organization.role)?.limited ?? false,
    organizationType: type,
  };
}

/** Every type of the deployment under its own roles, the owner and a reader. */
function memberships(kind: string): OrganizationSummary[] {
  // Through `organizationType`: the generated profile types an empty list of
  // roles as `never[]`.
  const types = deployment.organizationTypes.map((type) =>
    organizationType(type.key),
  );
  return types.flatMap((type) =>
    [
      { key: "owner", permissions: EVERYTHING },
      { key: "viewer", permissions: ["organization.read"] },
      ...type.roles.map((role) => ({
        key: role.key,
        permissions: [...role.permissions],
      })),
    ].map((role) => ({
      id: "019f0000-0000-7000-8000-000000000001",
      name: "Firma",
      slug: "firma",
      workspace_kind: kind,
      organization_type: type.key,
      status: "active",
      default_locale: "pl",
      timezone: "Europe/Warsaw",
      currency: "PLN",
      version: 1,
      membership_status: "active",
      role: role.key,
      permissions: role.permissions,
      active: true,
    })),
  );
}

describe("panel firmy nie zależy od panelu wydawcy", () => {
  it.each(["business", "personal"])(
    "workspace „%s”: dostęp, menu, dolny pasek i zakładki jak dotąd, w każdym typie i roli",
    (kind) => {
      const checked = memberships(kind);
      expect(checked.length).toBeGreaterThan(0);
      for (const membership of checked) {
        const access = panelAccess(membership);
        const was = before(membership);
        expect(access).toEqual(was);
        expect(access).not.toHaveProperty("publisher");
        // With the day's counts and an operator's level, as the layout adds them.
        for (const extra of [
          {},
          {
            operatorLevel: 1,
            booking: { bookableStaff: 3, teams: 1, waiting: 2, stays: true },
          },
        ]) {
          expect(panelNavigation({ ...access, ...extra })).toEqual(
            panelNavigation({ ...was, ...extra }),
          );
          expect(mobileTabs({ ...access, ...extra })).toEqual(
            mobileTabs({ ...was, ...extra }),
          );
          for (const path of PATHS)
            expect(sectionTabs(path, { ...access, ...extra })).toEqual(
              sectionTabs(path, { ...was, ...extra }),
            );
        }
      }
    },
  );

  it("wydawcą jest tylko workspace platformy", () => {
    for (const membership of memberships("platform")) {
      const access = panelAccess(membership);
      expect(access.publisher).toBe(true);
      expect(
        access.modules.filter(
          (module) =>
            module.startsWith("shared.billing") ||
            module.startsWith("shared.booking"),
        ),
      ).toEqual([]);
      // The team, the subscription and the calendar are a company's.
      const menu = panelNavigation(access);
      expect(
        [...menu.work, ...menu.company]
          .map((item) => item.href)
          .filter((href) =>
            ["/panel/team", "/panel/settings/billing", "/panel/calendar"].some(
              (core) => href === core || href.startsWith(`${core}/`),
            ),
          ),
      ).toEqual([]);
    }
  });
});
