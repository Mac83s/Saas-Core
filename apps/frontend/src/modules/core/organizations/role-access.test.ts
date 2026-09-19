import { expect, test } from "vitest";

import { roleAccess } from "./role-access";

// Core's global roles as the Business profile composes them (with farms).
const viewer = [
  "organization.read",
  "notifications.preferences",
  "booking.appointment.read",
  "farms.read",
];
const staff = [...viewer, "organization.members.read"];
const manager = [
  ...staff,
  "organization.members.manage_limited",
  "site.content.edit",
  "media.read",
  "media.manage",
  "notifications.manage",
  "booking.appointment.manage",
  "profiles.manage",
  "seo.audit.read",
  "farms.manage",
];
const admin = [
  ...manager,
  "organization.members.manage",
  "organization.settings.manage",
  "site.publish",
  "notifications.support",
  "integrations.manage",
];
const owner = [
  ...admin,
  "organization.billing.manage",
  "organization.ownership.transfer",
  "organization.archive",
  "vertical.records.read",
  "vertical.records.manage",
];
const offered = owner;

test("właściciel ma wszystko, administrator wszystko poza kilkoma obszarami", () => {
  expect(roleAccess(owner, offered)).toEqual({ kind: "full" });
  expect(
    roleAccess(
      [...admin, "vertical.records.read", "vertical.records.manage"],
      offered,
    ),
  ).toEqual({ kind: "except", areas: ["billing", "ownership"] });
  // Without the product's own permissions it is not "nearly everything".
  expect(roleAccess(admin, offered).kind).toBe("list");
});

test("rola z samym podglądem wymienia go i to, czego nie widzi", () => {
  expect(roleAccess(staff, offered)).toEqual({
    kind: "list",
    edit: [],
    view: ["bookings", "farms", "team"],
    also: [],
    none: ["settings", "billing"],
  });
});

test("uprawnienia produktu opisuje ich własną etykietą, silniejszą z grupy", () => {
  expect(
    roleAccess(
      [
        ...viewer,
        "media.manage",
        "vertical.records.read",
        "vertical.records.manage",
      ],
      offered,
    ),
  ).toEqual({
    kind: "list",
    edit: ["files"],
    view: ["bookings", "farms"],
    also: ["vertical.records.manage"],
    none: ["team", "settings", "billing"],
  });
});

test("rola bez żadnego obszaru ma tylko podstawowy dostęp", () => {
  expect(
    roleAccess(["organization.read", "notifications.preferences"], offered),
  ).toEqual({ kind: "basic" });
});
