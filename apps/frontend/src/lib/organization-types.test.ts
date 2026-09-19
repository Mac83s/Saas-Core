import { describe, expect, it, vi } from "vitest";

vi.mock("../generated/deployment", () => ({
  deployment: {
    modules: ["core.identity", "shared.billing", "shared.sites", "vertical.x"],
    organizationTypes: [
      {
        key: "company",
        label: { pl: "Firma", en: "Company" },
        description: null,
        modules: ["shared.billing", "shared.sites", "vertical.x"],
        planKeys: ["pro"],
        selfSignup: true,
      },
      {
        key: "farm",
        label: { pl: "Gospodarstwo", en: "Farm" },
        description: null,
        modules: ["shared.billing"],
        planKeys: ["farm"],
        selfSignup: false,
      },
    ],
  },
}));

const { modulesFor, organizationType, selfSignupTypes } =
  await import("./organization-types");

describe("typy organizacji (ADR-050)", () => {
  it("daje organizacji rdzeń i moduły jej typu", () => {
    expect([...modulesFor("farm")]).toEqual([
      "core.identity",
      "shared.billing",
    ]);
    expect(modulesFor("company").has("vertical.x")).toBe(true);
  });

  it("nieznany typ to typ domyślny, a rejestracja widzi tylko samodzielne", () => {
    expect(organizationType("nie-ma").key).toBe("company");
    expect(selfSignupTypes.map((type) => type.key)).toEqual(["company"]);
  });
});
