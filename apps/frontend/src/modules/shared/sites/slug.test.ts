import { expect, test } from "vitest";

import shared from "../../../../../../packages/contracts/locales/slug-cases.json";
import { slugFromTitle, slugifyTitle } from "./slug";

// The cases the backend's `slug_from_title` answers too.
test.each(shared.cases)(
  "makes the address the backend makes: $title",
  ({ title, slug }) => {
    expect(slugFromTitle(title)).toBe(slug);
  },
);

test("cuts a long title without a trailing hyphen", () => {
  const slug = slugFromTitle("Strzyżenie ".repeat(20), 30);
  expect(slug.length).toBeLessThanOrEqual(30);
  expect(slug.endsWith("-")).toBe(false);
});

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
