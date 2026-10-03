import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { PublicSitePage } from "@saas-core/api-client";
import { PublicSiteHead } from "./public-head";

const AI =
  "https://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia";

function page(overrides: Partial<PublicSitePage>): PublicSitePage {
  return {
    describedby: "https://studio.example.test/de/llms.txt",
    structured_data: { "@context": "https://schema.org", "@graph": [] },
    machine_text: null,
    ...overrides,
  } as PublicSitePage;
}

test("a version a machine wrote says so in the head, whatever the visible notice does", () => {
  for (const notice of [false, true]) {
    const html = renderToStaticMarkup(
      <PublicSiteHead
        page={page({
          machine_text: { source_type: AI, reviewed: !notice, notice },
        })}
      />,
    );
    expect(html).toContain(
      `<meta content="${AI}" name="digital-source-type"/>`,
    );
  }
});

test("a person's text carries no source-type mark, and keeps its map and structured data", () => {
  const html = renderToStaticMarkup(<PublicSiteHead page={page({})} />);

  expect(html).not.toContain("digital-source-type");
  expect(html).toContain(
    '<link href="https://studio.example.test/de/llms.txt" rel="describedby" type="text/plain"/>',
  );
  // The structured data went through `JsonLd` (the only printer of it).
  expect(html).toContain('"@context":"https://schema.org"');
});

test("a page from before these fields prints nothing", () => {
  const html = renderToStaticMarkup(
    <PublicSiteHead
      page={page({
        describedby: undefined,
        structured_data: undefined,
        machine_text: undefined,
      })}
    />,
  );
  expect(html).toBe("");
});
