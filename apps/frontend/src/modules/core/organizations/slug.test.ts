import { expect, test } from "vitest";

import { slugFromName } from "./slug";

test("slug z nazwy jest bez polskich znaków i z losową końcówką", () => {
  const slug = slugFromName("Gospodarstwo Łąka Żółta");
  expect(slug).toMatch(/^gospodarstwo-laka-zolta-[a-z0-9]{1,4}$/);
  expect(slugFromName("!!!")).toMatch(/^organizacja-[a-z0-9]{1,4}$/);
  expect(slugFromName("Nowak")).not.toBe(slugFromName("Nowak"));
});
