import { expect, test } from "vitest";

import { companyLocales } from "./company-locales";

test("offers the company's languages in its order, named in themselves", () => {
  const state = {
    public_locales: ["de", "pl"],
    version: 3,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "de", native_name: "Deutsch", english_name: "German" },
    ],
    limit: { allowed: true, additional_max: null, reason: "" },
    protected: {},
  };

  expect(companyLocales(state, ["pl", "en"])).toEqual([
    { code: "de", name: "Deutsch" },
    { code: "pl", name: "Polski" },
  ]);
});

test("names the fallback until the company's answer comes", () => {
  expect(companyLocales(undefined, ["pl", "en"])).toEqual([
    { code: "pl", name: "Polski" },
    { code: "en", name: "English" },
  ]);
});
