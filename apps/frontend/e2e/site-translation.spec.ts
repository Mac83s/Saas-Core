import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  chromium,
  expect as baseExpect,
  test,
  type Browser,
} from "@playwright/test";

// A page translated automatically, end to end on a running stack (TL15d): a
// company that reviews translations orders the German version of its home
// page from the editor's language mode, the worker translates it, the version
// waits, a person accepts it and reads it in the fields, and the published
// site answers in German under /de/. The translator is the stand-in (`fake/echo`, every
// fragment back with "[de] " in front) for this one synthetic w6-e2e-*
// company, so no real model is called and nothing is paid. How to run it:
// e2e/site-catalog.md.

// Orders, the worker and publications take a moment on a loaded host.
const expect = baseExpect.configure({ timeout: 20_000 });
const env = process.env;
const here = path.dirname(fileURLToPath(import.meta.url));
const runId = randomUUID().replaceAll("-", "").slice(0, 10);
const slug = `w6-e2e-translate-${runId}`;
// The environment of site-translation-run.sh, which owns the fixture.
const account = {
  SITE_CATALOG_SLUG: slug,
  SITE_CATALOG_EMAIL: `${slug}@example.test`,
  SITE_CATALOG_PASSWORD: `W6-E2E-${randomUUID()}-aA1!`,
};

const HEADING = `Studio wnętrz ${runId}`;
const TEXT = "Projektujemy mieszkania i biura od 2010 roku.";

function fixture(action: "prepare" | "cleanup") {
  execFileSync("bash", [path.join(here, "site-translation-run.sh"), action], {
    env: { ...env, ...account },
    stdio: "inherit",
  });
}

test.describe("A page translated by the stand-in and accepted by a person", () => {
  test.skip(
    env.SITE_TRANSLATION_E2E !== "1",
    "Creates a synthetic account, a site and a translation order on a live stack with MODEL_PORT_TEST_DOUBLE; run it with SITE_TRANSLATION_E2E=1 (e2e/site-catalog.md).",
  );
  test.use({ viewport: { width: 1440, height: 900 } });
  test.beforeAll(() => fixture("prepare"));
  test.afterAll(() => fixture("cleanup"));

  test("orders in review mode, the version waits, a person accepts it; /de/ answers in German", async ({
    page,
  }, testInfo) => {
    test.setTimeout(300_000);
    page.setDefaultTimeout(30_000);
    const origin = new URL(String(testInfo.project.use.baseURL)).origin;
    const panelErrors: string[] = [];
    const publicErrors: string[] = [];
    page.on("pageerror", (error) => panelErrors.push(error.message));

    const api = async <T>(method: string, url: string, data?: unknown) => {
      const csrf = (await page.context().cookies()).find(
        (cookie) => cookie.name === "csrftoken",
      )?.value;
      const response = await page.request.fetch(url, {
        method,
        data,
        headers: {
          "X-CSRFToken": csrf ?? "",
          Origin: origin,
          Referer: `${origin}/panel/sites`,
          ...(method === "GET" ? {} : { "Idempotency-Key": randomUUID() }),
        },
      });
      if (!response.ok())
        throw new Error(
          `${method} ${url}: ${response.status()} ${(await response.text()).slice(0, 600)}`,
        );
      return (await response.json()) as T;
    };

    let pageId = "";
    let hostname = "";

    await test.step("logs in; the company adds German and reviews translations", async () => {
      await page.goto("/login?next=/panel/sites");
      await page
        .getByLabel("E-mail", { exact: true })
        .fill(account.SITE_CATALOG_EMAIL);
      await page
        .getByLabel("Hasło", { exact: true })
        .fill(account.SITE_CATALOG_PASSWORD);
      await page
        .getByRole("button", { name: "Zaloguj się", exact: true })
        .click();
      await page.waitForURL((url) => url.pathname === "/panel/sites");

      // The same calls the panel's settings pages make, as the person.
      const locales = await api<{ version: number }>(
        "GET",
        "/api/v1/organizations/current/public-locales/",
      );
      await api("PUT", "/api/v1/organizations/current/public-locales/", {
        public_locales: ["pl", "de"],
        expected_version: locales.version,
      });
      const settings = await api<{ version: number }>(
        "GET",
        "/api/v1/translation/settings/",
      );
      await api("PATCH", "/api/v1/translation/settings/", {
        mode: "review",
        processing_acknowledged: true,
        expected_version: settings.version,
      });
      const offer = await api<{ available: boolean; reasons: string[] }>(
        "GET",
        "/api/v1/translation/offer/",
      );
      expect(offer.reasons).toEqual([]);
      expect(offer.available).toBe(true);
    });

    await test.step("publishes a Polish site with one page", async () => {
      const site = await api<{ id: string }>("POST", "/api/v1/sites/", {
        name: `Tłumaczenia e2e ${runId}`,
        slug,
        default_locale: "pl",
      });
      const created = await api<{ id: string }>(
        "POST",
        `/api/v1/sites/${site.id}/pages/`,
        { name: "Start", key: "start" },
      );
      pageId = created.id;
      await api("PUT", `/api/v1/sites/pages/${pageId}/draft/`, {
        expected_version: 0,
        blocks: [
          {
            block_type: "core.hero",
            schema_version: 6,
            data: { title: HEADING, text: TEXT },
          },
        ],
        media_asset_ids: [],
      });
      await api("PUT", `/api/v1/sites/pages/${pageId}/translations/pl/`, {
        expected_version: 0,
        slug: "start",
        title: "Start",
        description: "Strona testu tłumaczeń.",
        allow_title_fallback: false,
        allow_description_fallback: false,
        allow_social_title_fallback: false,
        allow_social_description_fallback: false,
      });
      await api("POST", `/api/v1/sites/${site.id}/publications/`);
      const domains = await api<{
        items: { hostname: string; is_canonical: boolean }[];
      }>("GET", `/api/v1/sites/${site.id}/domains/`);
      hostname = domains.items.find((domain) => domain.is_canonical)!.hostname;
    });

    const picker = page.getByRole("combobox", { name: "Wersja językowa" });

    await test.step("gives the German version its address", async () => {
      await page.goto(`/panel/sites/pages/${pageId}?language=de`);
      await expect(picker).toBeVisible();
      await page.getByRole("button", { name: "Nadaj adres i tytuł" }).click();
      const address = page.getByRole("dialog", { name: /^Adres i opis/ });
      const saveAddress = address.getByRole("button", {
        name: "Zapisz adres i opis",
      });
      // The fields open once the language's metadata has arrived, so what
      // is typed stays.
      await address.getByLabel("Tytuł strony", { exact: true }).fill("Start");
      await address
        .getByLabel("Opis w wyszukiwarce", { exact: true })
        .fill("Testseite der Übersetzungen.");
      await saveAddress.click();
      await expect(address).toBeHidden();
    });

    await test.step("orders the translation: the dialog says what it costs and that it will wait", async () => {
      await page.getByRole("button", { name: "Przetłumacz (AI)" }).click();
      const order = page.getByRole("dialog", {
        name: "Przetłumaczyć automatycznie?",
      });
      await expect(
        order.getByText(/^Do przetłumaczenia: \d+ znak/),
      ).toBeVisible();
      await expect(order.getByText(/Koszt: 1 kredyt\./)).toBeVisible();
      // "Po akceptacji": the finished text does not go out by itself.
      await expect(
        order.getByText(/Gotowe tłumaczenie poczeka na Twoją akceptację/),
      ).toBeVisible();
      const ordered = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/v1/translation/jobs/") &&
          response.request().method() === "POST",
      );
      await order
        .getByRole("button", { name: "Przetłumacz", exact: true })
        .click();
      expect([200, 201, 202]).toContain((await ordered).status());
      // The order runs on the server; the dialog may be closed meanwhile.
      await expect(
        order.getByText(/Tłumaczenie gotowe|Tłumaczenie trwa/),
      ).toBeVisible();
      await order.getByRole("button", { name: "Zamknij" }).click();
    });

    await test.step("the version waits for a person; nothing is on the site yet", async () => {
      await expect(
        page.getByText(/Tłumaczenie czeka na Twoją decyzję/),
      ).toBeVisible({ timeout: 90_000 });
      // The waiting words are read in the fields before the decision, and
      // nothing offers to order them again.
      await expect
        .poll(() =>
          page
            .locator("input, textarea")
            .evaluateAll((fields) =>
              fields.map((field) => (field as HTMLInputElement).value),
            ),
        )
        .toContain(`[de] ${HEADING}`);
      await expect(page.getByText(/nie ma jeszcze wersji/)).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: /Przetłumacz/ }),
      ).toHaveCount(0);
      // Nothing is on the site before the decision.
      const before = await page.request.get(`${origin}/de/`, {
        headers: { Host: hostname },
        maxRedirects: 0,
      });
      expect(before.status()).not.toBe(200);
    });

    await test.step("accepts and publishes the German version", async () => {
      await page
        .getByRole("button", { name: "Zaakceptuj i opublikuj" })
        .click();
      const decision = page.getByRole("dialog", {
        name: "Zaakceptować tłumaczenie i opublikować je?",
      });
      await decision
        .getByRole("button", { name: "Zaakceptuj i opublikuj" })
        .click();
      await expect(
        page.getByText("Tłumaczenie zaakceptowane i opublikowane."),
      ).toBeVisible();
      await expect(page.getByText("Ta wersja jest na stronie.")).toBeVisible();
      // The accepted version is in the fields, beside its source.
      await expect(
        page.getByText(HEADING, { exact: true }).first(),
      ).toBeVisible();
      await expect
        .poll(() =>
          page
            .locator("input, textarea")
            .evaluateAll((fields) =>
              fields.map((field) => (field as HTMLInputElement).value),
            ),
        )
        .toContain(`[de] ${HEADING}`);
    });

    // The published site under its own host, through the stack's Caddy,
    // set up like sites-publication.spec.ts.
    let browser: Browser | undefined;
    try {
      await test.step("the site answers in German under /de/", async () => {
        browser = await chromium.launch({
          channel: "chromium",
          args: [
            `--host-resolver-rules=MAP ${hostname} ${new URL(origin).host}`,
            `--unsafely-treat-insecure-origin-as-secure=http://${hostname}`,
          ],
        });
        const visitors = await browser.newContext({ locale: "de-DE" });
        await visitors.route(`http://${hostname}/**`, (route) =>
          route.continue({
            headers: {
              ...route.request().headers(),
              "x-forwarded-proto": "https",
            },
          }),
        );
        const visitor = await visitors.newPage();
        visitor.on("pageerror", (error) => publicErrors.push(error.message));
        const response = await visitor.goto(`http://${hostname}/de/`);
        expect(response?.status()).toBe(200);
        await expect(visitor.locator("html")).toHaveAttribute("lang", "de");
        await expect(
          visitor.getByRole("heading", {
            name: `[de] ${HEADING}`,
            exact: true,
          }),
        ).toBeVisible();
        await expect(visitor.getByText(`[de] ${TEXT}`)).toBeVisible();
        // The Polish page is as it was, and each names the other.
        const polish = await visitor.goto(`http://${hostname}/`);
        expect(polish?.status()).toBe(200);
        await expect(
          visitor.getByRole("heading", { name: HEADING, exact: true }),
        ).toBeVisible();
        await expect(
          visitor.getByRole("link", { name: "Deutsch", exact: true }),
        ).toHaveAttribute("href", "/de/");
      });
    } finally {
      await browser?.close();
    }

    expect(panelErrors).toEqual([]);
    expect(publicErrors).toEqual([]);
  });
});
