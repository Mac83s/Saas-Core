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
    // `suppressHydrationWarning` is React's own and leaves no attribute.
    expect(html).toContain('<html lang="en" dir="ltr" class="site-font">');
    expect(html).toContain("<main>page</main>");
    expect(server.setRequestLocale).toHaveBeenCalledWith("en");
  });

  it("lets a dark-mode script change <html> before hydration without a report", async () => {
    // The script writes `data-color-scheme` on <html> before React hydrates
    // (`COLOR_SCHEME_SCRIPT`); React reports an attribute it did not render
    // unless the element says the difference is expected.
    const document = await SiteDocument({
      locale: "en",
      namespaces: [],
      children: null,
    });

    expect(document.type).toBe("html");
    expect(document.props.suppressHydrationWarning).toBe(true);
    // One element deep: the body and the pages below report as ever.
    expect(document.props.children.type).toBe("body");
    expect(
      document.props.children.props.suppressHydrationWarning,
    ).toBeUndefined();
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
