import { expect, test } from "vitest";

import { slugifyTitle } from "./slug";

test("folds Polish letters instead of dropping them", () => {
  // Unicode normalisation cannot decompose ł, so a naive strip-the-marks
  // implementation deletes it: "Łódź" would come out as "odz".
  expect(slugifyTitle("Łódź")).toBe("lodz");
  expect(slugifyTitle("Zażółć gęślą jaźń")).toBe("zazolc-gesla-jazn");
  expect(slugifyTitle("Gabinet Łukasza")).toBe("gabinet-lukasza");
});

test("produces a key the page schema accepts", () => {
  const pattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  for (const title of [
    "O nas",
    "Cennik i FAQ",
    "  Kontakt  ",
    "Usługi 24/7",
    "Café Świeży",
  ]) {
    expect(slugifyTitle(title)).toMatch(pattern);
  }
});

test("returns an empty string when nothing survives", () => {
  // The caller shows this as "no suggestion yet" rather than letting an
  // invalid value reach the field.
  expect(slugifyTitle("")).toBe("");
  expect(slugifyTitle("!!!")).toBe("");
  expect(slugifyTitle("   ")).toBe("");
});
