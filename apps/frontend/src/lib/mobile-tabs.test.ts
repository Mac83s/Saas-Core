import { beforeEach, describe, expect, it, vi } from "vitest";

// A product slot the tests rewrite: the bottom bar is the product's to name.
const { slot } = vi.hoisted(() => ({
  slot: { product: {} as { mobileTabs?: string[] } },
}));
vi.mock("../product", () => slot);

import { mobileTabs, type PanelAccess } from "./panel-navigation";

const OWNER: PanelAccess = {
  modules: ["shared.booking", "shared.inventory", "shared.sites"],
  permissions: null,
  isOwner: true,
  limited: false,
};
const labels = (access: PanelAccess) =>
  mobileTabs(access).map((tab) => tab.labelKey);

beforeEach(() => {
  slot.product = {};
});

describe("dolny pasek na telefonie (UX-083)", () => {
  it("bez wskazania produktu to trzy pierwsze pozycje pracy, jak dotąd", () => {
    expect(labels(OWNER)).toEqual(["today", "calendar", "inventory"]);
  });

  it("produkt wskazuje pozycje po adresie z menu, także spoza grupy Praca", () => {
    slot.product = {
      mobileTabs: ["/panel", "/panel/calendar", "/panel/sites"],
    };
    expect(labels(OWNER)).toEqual(["today", "calendar", "website"]);
    // The entry opens where the menu opens it.
    expect(mobileTabs(OWNER)[2].href).toBe("/panel/sites");
  });

  it("pozycja, której osoba nie otworzy, wypada, a pasek dopełnia menu pracy", () => {
    slot.product = {
      mobileTabs: ["/panel", "/panel/calendar", "/panel/sites"],
    };
    // A worker without the website: the warehouse they work with comes back.
    const worker: PanelAccess = {
      ...OWNER,
      isOwner: false,
      permissions: ["booking.appointment.read", "inventory.read"],
    };
    expect(labels(worker)).toEqual(["today", "calendar", "inventory"]);
    // A product without the modules: whatever of the work menu is left.
    expect(labels({ ...OWNER, modules: [] })).toEqual(["today"]);
    // An address nobody declared is ignored, not an error.
    slot.product = { mobileTabs: ["/panel/nowhere", "/panel/sites"] };
    expect(labels(OWNER)).toEqual(["website", "today", "calendar"]);
  });
});
