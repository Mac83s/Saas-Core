import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  setRequestLocale: vi.fn(),
  getMessages: vi.fn(async () => ({
    Common: { save: "Save" },
    DashboardNav: { sites: "Sites" },
    PublicBooking: { email: "E-mail" },
    Site: { menu: "Breeds" },
  })),
}));

vi.mock("next-intl/server", () => server);
// The provider's own work is next-intl's; what it is handed is tested here.
vi.mock("next-intl", async (original) => ({
  ...(await original<typeof import("next-intl")>()),
  NextIntlClientProvider: ({
    messages,
    children,
  }: {
    messages: Record<string, unknown>;
    children: ReactNode;
  }) => <div data-shipped={Object.keys(messages).join(",")}>{children}</div>,
}));

import { SiteDocument, siteStaticParams } from "./site-document";

describe("the document of a product's public pages (ADR-080)", () => {
  it("ships the browser the named namespaces only, not the language's catalogue", async () => {
    const html = renderToStaticMarkup(
      await SiteDocument({
        locale: "en",
        namespaces: ["Site", "Common", "NoSuchNamespace"],
        className: "site-font",
        children: <main>page</main>,
      }),
    );

    expect(html).toContain('data-shipped="Site,Common"');
    expect(html).toContain('<html lang="en" dir="ltr" class="site-font">');
    expect(html).toContain("<main>page</main>");
    expect(server.setRequestLocale).toHaveBeenCalledWith("en");
  });

  it("answers 404 for a language the deployment does not route", async () => {
    await expect(
      SiteDocument({ locale: "xx", namespaces: [], children: null }),
    ).rejects.toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("names every routed language for static rendering", () => {
    expect(siteStaticParams()).toContainEqual({ locale: "pl" });
    expect(siteStaticParams()).toContainEqual({ locale: "en" });
  });
});
