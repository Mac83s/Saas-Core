import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { coreSiteBlockManifest } from "./core-manifest";
import { InvalidBlockDataError } from "./errors";
import { linkRel } from "./link-rel";
import { createSiteBlockRegistry } from "./registry";
import type { JsonObject } from "./types";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

describe("link rel (ADR-061)", () => {
  it("adds how a link vouches to what an outbound link always carried", () => {
    expect(linkRel("https://partner.test/", "sponsored")).toBe(
      "noreferrer sponsored",
    );
    expect(linkRel("https://partner.test/")).toBe("noreferrer");
    expect(linkRel("/kontakt/", "nofollow")).toBe("nofollow");
    expect(linkRel("/kontakt/")).toBeUndefined();
  });

  it("renders rel on a rich text link and refuses it before v4", () => {
    const content: JsonObject[] = [
      {
        type: "paragraph",
        content: [
          { text: "Polecamy " },
          { text: "partnera", href: "https://partner.test/", rel: "sponsored" },
        ],
      },
    ];
    const markup = renderToStaticMarkup(
      registry.render(
        { block_type: "core.rich_text", schema_version: 4, data: { content } },
        "a",
      ),
    );
    expect(markup).toContain('rel="noreferrer sponsored"');
    expect(() =>
      registry.validate({
        block_type: "core.rich_text",
        schema_version: 3,
        data: { content },
      }),
    ).toThrow(InvalidBlockDataError);
    // A rel with nothing to link is not a link.
    expect(() =>
      registry.validate({
        block_type: "core.rich_text",
        schema_version: 4,
        data: {
          content: [
            { type: "paragraph", content: [{ text: "x", rel: "ugc" }] },
          ],
        },
      }),
    ).toThrow(InvalidBlockDataError);
  });

  it("renders rel on link list and footer links", () => {
    const list = renderToStaticMarkup(
      registry.render(
        {
          block_type: "core.link_list",
          schema_version: 2,
          data: {
            links: [
              {
                label: "Sklep",
                href: "https://partner.test/",
                rel: "sponsored",
              },
            ],
          },
        },
        "l",
      ),
    );
    const footer = renderToStaticMarkup(
      registry.render(
        {
          block_type: "core.footer",
          schema_version: 2,
          data: {
            text: "Firma",
            links: [
              {
                label: "Wykonanie",
                href: "https://studio.test/",
                rel: "nofollow",
              },
            ],
          },
        },
        "f",
      ),
    );
    expect(list).toContain('rel="noreferrer sponsored"');
    expect(footer).toContain('rel="noreferrer nofollow"');
  });

  it("migrates older link blocks unchanged", () => {
    const footer = {
      block_type: "core.footer",
      schema_version: 1,
      data: { text: "Firma", links: [{ label: "O nas", href: "/o-nas/" }] },
    };
    expect(registry.migrate(footer)).toEqual({ ...footer, schema_version: 2 });
  });
});
