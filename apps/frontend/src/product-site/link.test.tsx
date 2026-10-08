import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fixtureDeployment, fixtureSite } from "./fixture";

async function load() {
  vi.resetModules();
  vi.doMock("../generated/deployment", () => ({
    deployment: fixtureDeployment(),
  }));
  vi.doMock("../product/public-site", () => ({ publicSite: fixtureSite }));
  return import("./link");
}

afterEach(() => {
  vi.doUnmock("../generated/deployment");
  vi.doUnmock("../product/public-site");
  vi.resetModules();
});

describe("a link to a product's public page (ADR-080)", () => {
  it("is written from the table, in the reader's language", async () => {
    const { SiteLink } = await load();

    render(
      <NextIntlClientProvider locale="de" messages={{}}>
        <SiteLink route="/breeds/[slug]" params={{ slug: "labrador" }}>
          Labrador
        </SiteLink>
        <SiteLink route="/" locale="pl">
          Polski
        </SiteLink>
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("link", { name: "Labrador" })).toHaveAttribute(
      "href",
      "/de/hunderassen/labrador",
    );
    const polish = screen.getByRole("link", { name: "Polski" });
    expect(polish).toHaveAttribute("href", "/");
    expect(polish).toHaveAttribute("hreflang", "pl");
  });

  it("fails where it is written when the page has no such language", async () => {
    const { SiteLink } = await load();
    vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() =>
      render(
        <NextIntlClientProvider locale="es" messages={{}}>
          <SiteLink route="/breeds">Razas</SiteLink>
        </NextIntlClientProvider>,
      ),
    ).toThrow(/no address for "\/breeds" in es/);
    vi.restoreAllMocks();
  });
});
