import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect as baseExpect, test, type Page } from "@playwright/test";

// The translations centre, end to end on a running stack (TL16g): a company
// that reviews translations orders everything that is missing from „Strona
// internetowa → Tłumaczenia” — its page and its card — follows the order to
// the end, accepts the card where its row stands (reading the proposal
// beside the source first), discards the page's version in „Do akceptacji”,
// orders it again and accepts it there, finds both orders in „Zadania” and
// nothing in „Wstrzymane”, and turns the automatic translation of changes
// on with its consent. The translator is the stand-in (`fake/echo`, every
// fragment back with "[de] " in front) for this one synthetic w6-e2e-*
// company: no real model is called and nothing is paid. How to run it:
// e2e/site-catalog.md.

// Orders, the worker and publications take a moment on a loaded host.
const expect = baseExpect.configure({ timeout: 20_000 });
const env = process.env;
const here = path.dirname(fileURLToPath(import.meta.url));
const runId = randomUUID().replaceAll("-", "").slice(0, 10);
const slug = `w6-e2e-centre-${runId}`;
// The environment of site-translation-run.sh, which owns the fixture.
const account = {
  SITE_CATALOG_SLUG: slug,
  SITE_CATALOG_EMAIL: `${slug}@example.test`,
  SITE_CATALOG_PASSWORD: `W6-E2E-${randomUUID()}-aA1!`,
};

const SITE = `Centrum e2e ${runId}`;
const CARD = `Pracownia ${runId}`;
const HEADING = `Meble na wymiar ${runId}`;
const TEXT = "Projektujemy i robimy meble od 2010 roku.";
const HEADLINE = `Stolarz z Mrągowa ${runId}`;
const BIO = "Robimy kuchnie, szafy i schody.";

function fixture(action: "prepare" | "cleanup") {
  execFileSync("bash", [path.join(here, "site-translation-run.sh"), action], {
    env: { ...env, ...account },
    stdio: "inherit",
  });
}

/** The order dialog: what it costs, the click, and the end of the job. */
async function order(page: Page, waits: RegExp) {
  const dialog = page.getByRole("dialog", {
    name: "Przetłumaczyć automatycznie?",
  });
  await expect(dialog.getByText(/^Do przetłumaczenia: \d+ znak/)).toBeVisible();
  await expect(dialog.getByText(/Koszt: \d+ kredyt/)).toBeVisible();
  await expect(dialog.getByText(waits).first()).toBeVisible();
  const ordered = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/translation/jobs/") &&
      response.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Przetłumacz", exact: true })
    .click();
  expect([200, 201, 202]).toContain((await ordered).status());
  // The order runs on the server: the dialog follows it to the end.
  await expect(dialog.getByText(/Tłumaczenie gotowe/)).toBeVisible({
    timeout: 90_000,
  });
  await dialog.getByRole("button", { name: "Zamknij" }).first().click();
  await expect(dialog).toBeHidden();
}

test.describe("The translations centre with the stand-in translator", () => {
  test.skip(
    env.SITE_TRANSLATION_E2E !== "1",
    "Creates a synthetic account, a site, a card and translation orders on a live stack with MODEL_PORT_TEST_DOUBLE; run it with SITE_TRANSLATION_E2E=1 (e2e/site-catalog.md).",
  );
  test.use({ viewport: { width: 1440, height: 900 } });
  test.beforeAll(() => fixture("prepare"));
  test.afterAll(() => fixture("cleanup"));

  test("order, progress, done on the card; accept and discard in the review; held and jobs; the automation's consent", async ({
    page,
  }, testInfo) => {
    test.setTimeout(420_000);
    page.setDefaultTimeout(30_000);
    const origin = new URL(String(testInfo.project.use.baseURL)).origin;
    const panelErrors: string[] = [];
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

    let siteId = "";
    let pageId = "";
    let cardId = "";
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

    await test.step("publishes a Polish site with one page and writes the company's card", async () => {
      const site = await api<{ id: string }>("POST", "/api/v1/sites/", {
        name: SITE,
        slug,
        default_locale: "pl",
      });
      siteId = site.id;
      const created = await api<{ id: string }>(
        "POST",
        `/api/v1/sites/${siteId}/pages/`,
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
      const metadata = {
        expected_version: 0,
        allow_title_fallback: false,
        allow_description_fallback: false,
        allow_social_title_fallback: false,
        allow_social_description_fallback: false,
      };
      await api("PUT", `/api/v1/sites/pages/${pageId}/translations/pl/`, {
        ...metadata,
        slug: "start",
        title: "Start",
        description: "Strona testu centrum tłumaczeń.",
      });
      // The German version's own address: a page is published under it.
      await api("PUT", `/api/v1/sites/pages/${pageId}/translations/de/`, {
        ...metadata,
        slug: "start",
        title: "Start",
        description: "Testseite des Übersetzungszentrums.",
      });
      await api("POST", `/api/v1/sites/${siteId}/publications/`);
      const domains = await api<{
        items: { hostname: string; is_canonical: boolean }[];
      }>("GET", `/api/v1/sites/${siteId}/domains/`);
      hostname = domains.items.find((domain) => domain.is_canonical)!.hostname;

      const card = await api<{ profile: { id: string; version: number } }>(
        "GET",
        "/api/v1/profiles/organization/",
      );
      cardId = card.profile.id;
      await api("PUT", `/api/v1/profiles/${cardId}/`, {
        expected_version: card.profile.version,
        display_name: CARD,
        headline: HEADLINE,
        bio: BIO,
      });
    });

    const overview = page.getByRole("table", {
      name: "Podstrony i wpisy w pozostałych językach strony",
    });
    const kind = page.getByLabel("Rodzaj", { exact: true });
    const rowOf = (name: string | RegExp) =>
      overview.getByRole("row").filter({ hasText: name });

    await test.step("the overview lists the page and, as their own rows, the company's card", async () => {
      await page.goto(`/panel/sites/translations?site=${siteId}`);
      // The German version has its address and not a word of its own yet.
      await expect(rowOf("Start").getByText("Niepełna")).toBeVisible();
      await kind.selectOption("other");
      const card = rowOf(CARD);
      await expect(card.getByText("Wizytówka")).toBeVisible();
      await expect(card.getByText("Brak")).toBeVisible();
      await expect(
        card.getByRole("link", { name: "Edytuj", exact: true }),
      ).toHaveAttribute("href", /\/panel\/profile$/);
    });

    await test.step("orders everything that is missing: the dialog follows the order to its end", async () => {
      await page
        .getByRole("button", {
          name: "Przetłumacz brakujące i nieaktualne (AI)",
        })
        .click();
      await order(page, /Gotowe tłumaczenie poczeka na Twoją akceptację/);
    });

    await test.step("the card's proposal is read beside its source and accepted where its row stands", async () => {
      const card = rowOf(CARD);
      await expect(card.getByText("Czeka na akceptację")).toBeVisible({
        timeout: 90_000,
      });
      // Two results wait: the tab says so.
      await expect(
        page.getByRole("link", { name: "Do akceptacji (2)" }),
      ).toBeVisible();
      await card
        .getByRole("button", { name: `Zaakceptuj: ${CARD} — Deutsch` })
        .click();
      const compare = page.getByRole("dialog", { name: `${CARD} · Deutsch` });
      await expect(compare.getByText(HEADLINE, { exact: true })).toBeVisible();
      await expect(
        compare.getByText(`[de] ${HEADLINE}`, { exact: true }),
      ).toBeVisible();
      await expect(
        compare.getByText(`[de] ${BIO}`, { exact: true }),
      ).toBeVisible();
      await compare
        .getByRole("button", { name: "Zaakceptuj i opublikuj" })
        .click();
      await expect(
        page.getByText("Tłumaczenie zaakceptowane i opublikowane."),
      ).toBeVisible();
      await expect(card.getByText("Przetłumaczona")).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Do akceptacji (1)" }),
      ).toBeVisible();
      // Done on the card itself: its German texts are the stand-in's.
      const german = await api<{
        languages: { locale: string; units: { key: string; text: string }[] }[];
      }>("GET", `/api/v1/profiles/${cardId}/translations/`);
      const units = german.languages.find(
        (language) => language.locale === "de",
      )!.units;
      expect(units.find((unit) => unit.key === "headline")?.text).toBe(
        `[de] ${HEADLINE}`,
      );
      expect(units.find((unit) => unit.key === "bio")?.text).toBe(
        `[de] ${BIO}`,
      );
    });

    const review = page.getByRole("table", {
      name: "Tłumaczenia czekające na decyzję",
    });
    const reason = page.getByLabel("Powód", { exact: true });

    await test.step("„Do akceptacji”: the filter is the server's; the page's version is discarded", async () => {
      await page.getByRole("link", { name: "Do akceptacji (1)" }).click();
      const waiting = review.getByRole("row").filter({ hasText: "Start" });
      await expect(waiting.getByText("Deutsch")).toBeVisible();
      await expect(
        waiting.getByText("Firma akceptuje tłumaczenia przed publikacją"),
      ).toBeVisible();
      await reason.selectOption("qa_flagged");
      await expect(waiting).toHaveCount(0);
      await reason.selectOption("review_mode");
      await expect(waiting).toHaveCount(1);
      await reason.selectOption("");

      await waiting
        .getByRole("button", { name: "Działania dla: Start · Deutsch" })
        .click();
      await page.getByRole("menuitem", { name: "Odrzuć" }).click();
      const question = page.getByRole("dialog", {
        name: "Odrzucić to tłumaczenie?",
      });
      await expect(question.getByText(/Kredyty .* nie wracają/)).toBeVisible();
      await question.getByRole("button", { name: "Odrzuć" }).click();
      await expect(page.getByText("Tłumaczenie odrzucone.")).toBeVisible();
      await expect(
        page.getByText("Nic nie czeka na Twoją decyzję."),
      ).toBeVisible();
      // Nothing went out: the site has no German page.
      const before = await page.request.get(`${origin}/de/`, {
        headers: { Host: hostname },
        maxRedirects: 0,
      });
      expect(before.status()).not.toBe(200);
    });

    await test.step("ordered again from the page's row and accepted in „Do akceptacji”: /de/ answers in German", async () => {
      await page.getByRole("link", { name: "Przegląd", exact: true }).click();
      const start = rowOf("Start");
      await expect(start.getByText("Niepełna")).toBeVisible();
      await start.getByRole("button", { name: "Działania dla: Start" }).click();
      await page.getByRole("menuitem", { name: "Przetłumacz (AI)" }).click();
      await order(page, /Gotowe tłumaczenie poczeka na Twoją akceptację/);
      await expect(start.getByText("Czeka na akceptację")).toBeVisible({
        timeout: 90_000,
      });
      // What waits can be read as visitors would get it, before the decision.
      await expect(
        start.getByRole("link", { name: "Podgląd: Start — Deutsch" }),
      ).toHaveAttribute(
        "href",
        new RegExp(`/panel/sites/pages/${pageId}\\?language=de&preview=1$`),
      );

      await page.getByRole("link", { name: "Do akceptacji (1)" }).click();
      const waiting = review.getByRole("row").filter({ hasText: "Start" });
      await waiting
        .getByRole("button", { name: "Zaakceptuj i opublikuj" })
        .click();
      await page
        .getByRole("dialog", {
          name: "Zaakceptować tłumaczenie i opublikować je?",
        })
        .getByRole("button", { name: "Zaakceptuj i opublikuj" })
        .click();
      await expect(
        page.getByText("Tłumaczenie zaakceptowane i opublikowane."),
      ).toBeVisible();

      const german = await page.request.get(`${origin}/de/`, {
        headers: { Host: hostname },
      });
      expect(german.status()).toBe(200);
      expect(await german.text()).toContain(`[de] ${HEADING}`);

      // The overview says so, with the way to the page on the site.
      await page.getByRole("link", { name: "Przegląd", exact: true }).click();
      await expect(rowOf("Start").getByText("Przetłumaczona")).toBeVisible();
      await expect(
        rowOf("Start").getByText("na stronie", { exact: true }),
      ).toBeVisible();
      await expect(
        rowOf("Start").getByRole("link", {
          name: "Otwórz na stronie: Start — Deutsch",
        }),
      ).toHaveAttribute("href", new RegExp(`${hostname}.*/de/$`));
    });

    await test.step("„Zadania” lists both orders; „Wstrzymane” holds nothing", async () => {
      await page.getByRole("link", { name: "Zadania", exact: true }).click();
      const jobs = page.getByRole("table", { name: "Zadania tłumaczeń" });
      await expect(
        jobs.getByRole("row").filter({ hasText: "Gotowe" }),
      ).toHaveCount(2);
      const state = page.getByLabel("Stan", { exact: true });
      await state.selectOption("active");
      await expect(
        jobs.getByRole("row").filter({ hasText: "Gotowe" }),
      ).toHaveCount(0);
      const held = page.waitForResponse((response) =>
        response.url().includes("/api/v1/translation/demand/"),
      );
      await state.selectOption("held");
      expect((await held).status()).toBe(200);
      await expect(
        page.getByRole("table", {
          name: "Wstrzymane zmiany do przetłumaczenia",
        }),
      ).toBeVisible();
      await expect(
        page.getByText("Automat zmian niczego teraz nie wstrzymuje."),
      ).toBeVisible();
    });

    await test.step("turning the automation on records the person's consent", async () => {
      await page.goto("/panel/settings/languages");
      const automation = page.getByRole("switch", {
        name: "Tłumacz zmiany automatycznie",
      });
      await expect(automation).not.toBeChecked();
      await automation.click();
      const consent = page.getByRole("dialog", {
        name: "Włączyć automatyczne tłumaczenie zmian?",
      });
      await expect(consent.getByText(/To Twoja zgoda/)).toBeVisible();
      await consent
        .getByRole("button", { name: "Włącz i wyraź zgodę" })
        .click();
      await expect(page.getByText(/^Działa w imieniu: /)).toBeVisible();
      await expect(automation).toBeChecked();
      const saved = await api<{
        values: Record<string, { value: unknown }>;
        automation: {
          consent_membership_id: string | null;
          consent_holds: boolean;
        };
      }>("GET", "/api/v1/translation/settings/");
      expect(saved.values["translation.settings.auto_changes"]?.value).toBe(
        true,
      );
      expect(saved.automation.consent_membership_id).not.toBeNull();
      expect(saved.automation.consent_holds).toBe(true);
    });

    expect(panelErrors).toEqual([]);
  });
});
