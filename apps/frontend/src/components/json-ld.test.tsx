import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { JsonLd } from "./json-ld";

test("a company's text stays inside the one script element", () => {
  const html = renderToStaticMarkup(
    <JsonLd data={{ name: '</script><script>alert("x")</script>' }} />,
  );

  expect(html.startsWith('<script type="application/ld+json">')).toBe(true);
  expect(html.match(/<\/script>/g)).toHaveLength(1);
  expect(html).not.toContain("<script>alert");
});
