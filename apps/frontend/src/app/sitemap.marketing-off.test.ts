import { expect, it, vi } from "vitest";

vi.mock("../modules/shared/profiles/catalog-server", () => ({
  readCatalogLocalesOnServer: vi.fn(),
  readCatalogSitemapOnServer: vi.fn(),
}));
// A product whose public site answers on its own domain (ADR-077).
vi.mock("../marketing/enabled", () => ({ marketingSiteEnabled: false }));

import { productHasCatalog } from "../marketing/content";
import sitemap from "./sitemap";

it("lists nothing where the profile switches the marketing off", async () => {
  expect(await sitemap()).toEqual([]);
  expect(productHasCatalog).toBe(false);
});
