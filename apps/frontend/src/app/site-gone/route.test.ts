import { describe, expect, it } from "vitest";

import {
  GONE_HOME_HEADER,
  GONE_LOCALE_HEADER,
} from "../../modules/shared/sites/gone-headers";
import { GET } from "./route";

function ask(headers: Record<string, string>) {
  return GET(new Request("http://stary.example.test/site-gone", { headers }));
}

describe("the 410 page (ADR-077)", () => {
  it("says it in the reader's language, with the way home", async () => {
    const response = ask({
      [GONE_LOCALE_HEADER]: "ru",
      [GONE_HOME_HEADER]: "/ru/",
    });
    expect(response.status).toBe(410);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(response.headers.get("x-robots-tag")).toBe("noindex");
    const html = await response.text();
    expect(html).toContain('<html lang="ru">');
    expect(html).toContain("<h1>Этой страницы больше нет</h1>");
    expect(html).toContain('<a href="/ru/">На главную страницу</a>');
  });

  it("reads English and links nowhere when the site is unknown", async () => {
    const html = await ask({}).text();
    expect(html).toContain('<html lang="en">');
    expect(html).toContain("This page is gone");
    expect(html).not.toContain("<a ");
  });

  it("never prints a header's value as markup or as a link off the site", async () => {
    const html = await ask({
      [GONE_LOCALE_HEADER]: '"><script>',
      [GONE_HOME_HEADER]: "https://evil.test/",
    }).text();
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("evil.test");
  });
});
