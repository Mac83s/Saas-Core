import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { coreSiteBlockManifest } from "./core-manifest";
import { InvalidBlockDataError } from "./errors";
import { fieldsOfOtherLayouts, hiddenFields } from "./hidden-fields";
import { createSiteBlockRegistry } from "./registry";
import { tableColumnCount } from "./table-block";
import type { JsonObject, SiteBlock } from "./types";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

function block(data: JsonObject): SiteBlock {
  return { block_type: "core.table", schema_version: 1, data };
}

const cell = (text: string) => ({ content: [{ text }] });
const prices = {
  caption: "Cennik strzyżenia",
  rows: [
    { cells: [cell("Usługa"), cell("Czas"), cell("Cena")] },
    { cells: [cell("Strzyżenie"), cell("60 min"), cell("120 zł")] },
    { cells: [cell("Kąpiel"), {}, cell("80 zł")] },
  ],
};

const render = (data: JsonObject, locale?: string) =>
  renderToStaticMarkup(
    registry.render(
      block(data),
      "table",
      undefined,
      undefined,
      undefined,
      locale ? { locale } : undefined,
    ),
  );

describe("core.table", () => {
  it("is a real table: a caption, a header row with column scope, a body", () => {
    const html = render(prices);
    expect(html).toContain('data-block-type="core.table"');
    expect(html).toContain("<caption>Cennik strzyżenia</caption>");
    expect(html).toContain(
      '<thead><tr><th scope="col">Usługa</th><th scope="col">Czas</th><th scope="col">Cena</th></tr></thead>',
    );
    expect(html).toContain(
      "<tbody><tr><td>Strzyżenie</td><td>60 min</td><td>120 zł</td></tr><tr><td>Kąpiel</td><td></td><td>80 zł</td></tr></tbody>",
    );
  });

  it("scrolls inside a named region a keyboard reaches, never the page", () => {
    expect(render(prices)).toContain(
      '<div class="site-table__scroll" role="region" aria-label="Cennik strzyżenia" tabindex="0">',
    );
    const { caption: _caption, ...unnamed } = prices;
    // Without a caption the region is named in the page's language.
    expect(render(unnamed)).toContain('aria-label="Tabela"');
    expect(render(unnamed, "de")).toContain('aria-label="Tabelle"');
    expect(render(unnamed, "ru")).toContain('aria-label="Таблица"');
  });

  it("names rows by the first column when the block says so", () => {
    const html = render({ ...prices, header: "both" });
    expect(html).toContain('<th scope="col">Usługa</th>');
    expect(html).toContain(
      '<tr><th scope="row">Strzyżenie</th><td>60 min</td>',
    );
    const columnOnly = render({ ...prices, header: "column" });
    expect(columnOnly).not.toContain("<thead>");
    expect(columnOnly).toContain(
      '<tr><th scope="row">Usługa</th><td>Czas</td>',
    );
    const none = render({ ...prices, header: "none" });
    expect(none).not.toContain("<th");
  });

  it("writes an empty header cell as a plain cell: it names nothing", () => {
    const html = render({
      header: "both",
      rows: [
        { cells: [{}, cell("Mały pies")] },
        { cells: [cell("Kąpiel"), cell("80 zł")] },
      ],
    });
    expect(html).toContain(
      '<thead><tr><td></td><th scope="col">Mały pies</th></tr></thead>',
    );
  });

  it("fills a shorter row, so the grid stays a rectangle", () => {
    const rows = [
      { cells: [cell("a"), cell("b"), cell("c")] },
      { cells: [cell("d")] },
    ];
    expect(tableColumnCount(rows)).toBe(3);
    expect(render({ header: "none", rows })).toContain(
      "<tr><td>d</td><td></td><td></td></tr>",
    );
  });

  it("gives a cell the marks rich text has, with the same markup", () => {
    const html = render({
      rows: [
        {
          cells: [
            {
              content: [
                { text: "Zobacz " },
                { text: "cennik", bold: true, href: "/cennik" },
                { text: " i " },
                {
                  text: "partnera",
                  italic: true,
                  href: "https://example.com/",
                  rel: "sponsored",
                },
              ],
            },
          ],
        },
        { cells: [cell("x")] },
      ],
    });
    expect(html).toContain(
      '<a class="site-prose__link" href="/cennik"><strong>cennik</strong></a>',
    );
    expect(html).toContain(
      '<a class="site-prose__link" href="https://example.com/" rel="noreferrer sponsored"><em>partnera</em></a>',
    );
  });

  it("hands every cell's text and the caption to the editor at its data path", () => {
    const seen: string[] = [];
    renderToStaticMarkup(
      registry.render(block(prices), "table", {
        text: (path, value) => {
          seen.push(`${path.join(".")}=${value}`);
          return h("span", null, value);
        },
      }),
    );
    expect(seen).toContain("caption=Cennik strzyżenia");
    expect(seen).toContain("rows.0.cells.2.content.0.text=Cena");
    expect(seen).toContain("rows.2.cells.0.content.0.text=Kąpiel");
  });

  it("holds the contract's limits and refuses markup in a cell", () => {
    const row = { cells: [cell("x")] };
    expect(() => registry.validate(block({ rows: [] }))).toThrow(
      InvalidBlockDataError,
    );
    expect(() =>
      registry.validate(
        block({ rows: Array.from({ length: 121 }, () => row) }),
      ),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        block({
          rows: [{ cells: Array.from({ length: 13 }, () => cell("x")) }],
        }),
      ),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        block({
          rows: [{ cells: [{ content: [{ text: "x", html: "<b>" }] }] }],
        }),
      ),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(
        block({
          rows: [
            {
              cells: [
                { content: [{ text: "x", href: "javascript:alert(1)" }] },
              ],
            },
          ],
        }),
      ),
    ).toThrow(InvalidBlockDataError);
    // An empty cell is `{}`; an empty run is not a cell's content.
    expect(() =>
      registry.validate(block({ rows: [{ cells: [{ content: [] }] }] })),
    ).toThrow(InvalidBlockDataError);
    expect(() =>
      registry.validate(block({ rows: [{ cells: [{}] }] })),
    ).not.toThrow();
  });

  it("shows every field in both layouts: none hides when the layout changes", () => {
    const filled = block({ ...prices, layout: "striped" });
    expect(render(filled.data)).toContain("site-table--striped");
    expect([...fieldsOfOtherLayouts(filled, registry)]).toEqual([]);
    expect(hiddenFields(filled, registry)).toEqual([]);
  });
});
