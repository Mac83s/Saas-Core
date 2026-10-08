import { NextRequest } from "next/server";

/**
 * The addresses the proxy's answers are recorded for (`proxy.golden.json`),
 * and how an answer is written down. Shared by the record itself and by the
 * tests of a product's public pages (ADR-080), which hold their answers
 * against it.
 */
export const PLATFORM_PATHS = [
  "/",
  "/pl",
  "/pl/",
  "/en",
  "/en/",
  "/de",
  "/de/",
  "/ru",
  "/fr",
  "/EN",
  "/pricing",
  "/pricing/",
  "/pricing?plan=pro",
  "/pricing/?plan=pro",
  "/pl/pricing",
  "/pl/pricing?plan=pro",
  "/en/pricing",
  "/de/pricing",
  "/Pricing",
  "/PL/pricing",
  "/contact",
  "/en/contact",
  "/katalog",
  "/pl/katalog",
  "/en/katalog",
  "/de/katalog",
  "/katalog/mragowo/salon",
  "/katalog/mragowo/salon/",
  "/de/katalog/mragowo/salon",
  "/regulamin",
  "/en/terms",
  "/nie-ma/takiej/strony",
  "/en/no/such/page",
  "/rasy-psow/labrador",
  "/en/dog-breeds/labrador",
  "/product-site",
  "/product-site/breeds/labrador",
  "/en/product-site",
  "/za%C5%BC%C3%B3%C5%82%C4%87",
  "/en/caf%C3%A9",
  "/%E0%A4%A",
  "/login",
  "/pl/login",
  "/en/login",
  "/de/login",
  "/register",
  "/en/register",
  "/onboarding",
  "/password-reset",
  "/reset-password",
  "/verify-email",
  "/panel",
  "/panel/",
  "/pl/panel",
  "/en/panel",
  "/de/panel",
  "/de/panel/settings?tab=team",
  "/panel/sites",
  "/panel/calendar",
  "/en/panel/calendar/day",
  "/settings/security",
  "/en/settings/security",
  "/invitations/abc",
  "/book/salon-anna",
  "/en/book/salon-anna",
  "/de/book/salon-anna",
  "/booking/abc",
  "/en/booking/abc",
  "/documents/regulamin",
  "/field/start",
  "/en/field/visits/1/trim",
  "/sitemap.xml",
  "/robots.txt",
  "/site-renderer",
  "/site-renderer/oferta/",
];

export const CUSTOMER_PATHS = [
  "/",
  "/oferta",
  "/oferta/",
  "/en/",
  "/en/blog/wpis/",
  "/pl/oferta/",
  "/panel",
  "/login",
  "/pricing",
  "/rasy-psow/labrador",
  "/stary-adres",
  "/sitemap.xml",
  "/robots.txt",
  "/rss.xml",
  "/en/llms.txt",
  "/site-renderer",
  "/site-renderer/oferta/",
];

/** A visitor with no preference, and one whose browser and cookie have one. */
export const VISITORS: Record<string, Record<string, string>> = {
  plain: {},
  "prefers en": {
    "accept-language": "en-GB,en;q=0.9,de;q=0.5",
    cookie: "NEXT_LOCALE=en",
  },
  "behind https": { "x-forwarded-proto": "https" },
};

export const HOSTS: Record<string, string[]> = {
  "localhost:8080": PLATFORM_PATHS,
  "platform.example.test": PLATFORM_PATHS,
  "studio.example.test": CUSTOMER_PATHS,
};

const REQUEST = "x-middleware-request-";

/** One line per answer: what a visitor and the page behind the proxy see. */
export function describeResponse(response: Response): string {
  const said: string[] = [String(response.status)];
  const header = (name: string) => response.headers.get(name);
  if (header("location")) said.push(`location=${header("location")}`);
  if (header("x-middleware-rewrite")) {
    said.push(`rewrite=${header("x-middleware-rewrite")}`);
  }
  if (header("x-middleware-next")) said.push("next");
  const forwarded: string[] = [];
  response.headers.forEach((value, name) => {
    if (!name.startsWith(REQUEST)) return;
    const key = name.slice(REQUEST.length);
    // The visitor's own headers travel on; only what the proxy says matters.
    if (key.startsWith("x-")) forwarded.push(`${key}=${value}`);
  });
  if (forwarded.length) said.push(`request[${forwarded.sort().join(", ")}]`);
  const cookies = response.headers.getSetCookie();
  if (cookies.length) said.push(`set-cookie[${cookies.join(" | ")}]`);
  if (header("link")) said.push(`link=${header("link")}`);
  return said.join(" ");
}

type Proxy = (request: NextRequest) => Response | Promise<Response>;

/** Every recorded address, as every kind of visitor, on every host. */
export async function walk(proxy: Proxy): Promise<Record<string, string>> {
  const answers: Record<string, string> = {};
  for (const [host, paths] of Object.entries(HOSTS)) {
    for (const [visitor, headers] of Object.entries(VISITORS)) {
      for (const address of paths) {
        const key = `${host} | ${visitor} | ${address}`;
        try {
          const response = await proxy(
            new NextRequest(`http://${host.split(":")[0]}${address}`, {
              headers: { host, ...headers },
            }),
          );
          answers[key] = describeResponse(response);
        } catch (error) {
          answers[key] = `throws ${(error as Error).name}`;
        }
      }
    }
  }
  return answers;
}
