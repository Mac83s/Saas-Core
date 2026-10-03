import { beforeEach, describe, expect, it, vi } from "vitest";

const organization = vi.hoisted(() => ({
  current: null as { organization_type: string } | null,
}));

vi.mock("next-intl/server", () => ({
  getLocale: async () => "pl",
  getTimeZone: async () => "Europe/Warsaw",
  getMessages: async () => core,
}));
vi.mock("#lib/server-auth", () => ({
  getServerCurrentOrganization: async () => organization.current,
}));
vi.mock("../product/organization-messages", () => ({
  default: {
    farm: { pl: { Profile: { title: "Wizytówka gospodarstwa" } } },
    shop: { pl: {} },
  },
}));

const core = {
  Profile: { title: "Wizytówka firmy", name: "Nazwa firmy" },
};

const { getPanelMessages, getPanelTranslations, typeMessages } =
  await import("./panel-messages");

describe("the panel's words for a kind of organization (UX-080)", () => {
  beforeEach(() => {
    organization.current = null;
  });

  it("lays a type's words over the product's, keeping every other key", async () => {
    organization.current = { organization_type: "farm" };
    const { messages, overridden } = await getPanelMessages();
    expect(overridden).toBe(true);
    expect(messages).toEqual({
      Profile: { title: "Wizytówka gospodarstwa", name: "Nazwa firmy" },
    });
    const t = await getPanelTranslations("Profile");
    expect(t("title")).toBe("Wizytówka gospodarstwa");
    expect(t("name")).toBe("Nazwa firmy");
  });

  it("gives an account without words of its type no second set of messages", async () => {
    organization.current = { organization_type: "trimming_company" };
    const { messages, overridden } = await getPanelMessages();
    expect(overridden).toBe(false);
    // The very set the root layout already sent, not a copy.
    expect(messages).toBe(core);
    expect((await getPanelTranslations("Profile"))("title")).toBe(
      "Wizytówka firmy",
    );
  });

  it("keeps the product's words when the type is unknown or has none here", () => {
    // No active company, or one that refuses the account until 2FA is on.
    expect(typeMessages(null, "pl")).toBeNull();
    expect(typeMessages("farm", "en")).toBeNull();
    expect(typeMessages("shop", "pl")).toBeNull();
    expect(typeMessages("farm", "pl")).toEqual({
      Profile: { title: "Wizytówka gospodarstwa" },
    });
  });
});
