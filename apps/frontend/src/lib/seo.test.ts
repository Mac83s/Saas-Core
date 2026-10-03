import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

import { serializeJsonLd } from "./seo";

const HOSTILE = {
  "@type": "Organization",
  name: '</script><script>alert("x")</script>',
  description: "A & B <!-- \u2028 line \u2029 end",
};

test("a company's text cannot end the JSON-LD block or the script", () => {
  const serialized = serializeJsonLd(HOSTILE);

  expect(serialized).not.toMatch(/[<>&\u2028\u2029]/);
  // Every escape is one JSON reads back: the data is unchanged.
  expect(JSON.parse(serialized)).toEqual(HOSTILE);
});

test("plain data is printed as the JSON it is", () => {
  expect(serializeJsonLd({ "@id": "https://a.test/#organization" })).toBe(
    '{"@id":"https://a.test/#organization"}',
  );
});

test("no page prints structured data past `JsonLd`", () => {
  // Tests run from apps/frontend.
  const source = join(process.cwd(), "src");
  const allowed =
    /(^|[\\/])(lib[\\/]seo(\.test)?\.ts|components[\\/]json-ld(\.test)?\.tsx)$/;
  const offenders = (
    readdirSync(source, { recursive: true, encoding: "utf8" }) as string[]
  )
    .filter((file) => /\.tsx?$/.test(file) && !allowed.test(file))
    .filter((file) =>
      readFileSync(join(source, file), "utf8").includes("application/ld+json"),
    );

  expect(offenders).toEqual([]);
});
