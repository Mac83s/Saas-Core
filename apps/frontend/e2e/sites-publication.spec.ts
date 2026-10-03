import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  chromium,
  expect as baseExpect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

// Site Studio end to end on a running stack: a new site through onboarding,
// a page from a whole-page template, the visual editor's canvas (inline
// text, keyboard reorder, "+" between sections, undo/redo from anywhere,
// viewports, "Zmień zdjęcie"), save, publish, a second publication and a
// rollback, each checked on the published site under its own host. It writes
// to the stack through a synthetic w6-e2e-* account, removed afterwards; how
// to run it: e2e/site-catalog.md.

// Imports, saves and publications take a moment on a loaded host.
const expect = baseExpect.configure({ timeout: 15_000 });
const env = process.env;
const here = path.dirname(fileURLToPath(import.meta.url));
const runId = randomUUID().replaceAll("-", "").slice(0, 10);
const slug = `w6-e2e-studio-${runId}`;
// The environment of site-catalog-run.sh, which owns the fixture.
const account = {
  SITE_CATALOG_SLUG: slug,
  SITE_CATALOG_EMAIL: `${slug}@example.test`,
  SITE_CATALOG_PASSWORD: `W6-E2E-${randomUUID()}-aA1!`,
};

const SITE_NAME = `Studio e2e ${runId}`;
const SUBDOMAIN = `e2e-studio-${runId}`;
const PAGE_NAME = "Oferta";
const PAGE_SLUG = "oferta";
// core.service_focused v2: seven sections, a photo bound to the hero.
const TEMPLATE = "Jedna usługa — konkret";
const PHOTO_ALT =
  "Krowy pasą się na zielonym pastwisku o wschodzie słońca, w tle drewniana obora i góry";
const FIRST_HEADING = `Korekcja racic, pierwsza wersja ${runId}`;
const SECOND_HEADING = `Korekcja racic, druga wersja ${runId}`;
const HEADING_FIELD = "Edytuj na podglądzie: Nagłówek";

interface Draft {
  version: number;
  blocks: { block_type: string; data: Record<string, unknown> }[];
}

function fixture(action: "prepare" | "cleanup") {
  execFileSync("bash", [path.join(here, "site-catalog-run.sh"), action], {
    env: { ...env, ...account },
    stdio: "inherit",
  });
}

/** Focus and caret moves settle before the next key on a loaded host. */
const settle = (page: Page) => page.waitForTimeout(200);

test.describe("Site Studio from a new site to a rolled-back publication", () => {
  test.skip(
    env.SITE_STUDIO_E2E !== "1",
    "Creates a synthetic account, a site and publications on a live stack; run it with SITE_STUDIO_E2E=1 (e2e/site-catalog.md).",
  );
  test.use({ viewport: { width: 1440, height: 900 } });
  test.beforeAll(() => fixture("prepare"));
  test.afterAll(() => fixture("cleanup"));

  test("onboards, builds a page on the canvas, publishes and rolls back", async ({
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

    const studio = page.getByRole("dialog", {
      name: `Edytor strony: ${PAGE_NAME}`,
    });
    const canvas = studio.getByTestId("live-canvas");
    const sections = canvas.locator("[data-section-index]");
    // The select button over each section reads "<n>. <kind>".
    const outline = canvas.getByRole("button", {
      name: /^Edytuj sekcję \d+: /,
    });
    const inspector = studio.getByRole("complementary", {
      name: "Edycja wybranej sekcji",
    });
    const library = page.getByRole("dialog", { name: "Wybierz sekcję" });
    const undo = studio.getByRole("button", { name: "Cofnij", exact: true });
    const redo = studio.getByRole("button", { name: "Ponów", exact: true });
    let pageId = "";
    let hostname = "";

    /** Clicks the selected section's heading on the canvas, types, Enter. */
    const editHeading = async (text: string) => {
      await canvas
        .getByRole("button", { name: HEADING_FIELD, exact: true })
        .click();
      const input = canvas.getByRole("textbox", {
        name: HEADING_FIELD,
        exact: true,
      });
      await expect(input).toBeFocused();
      await input.fill(text);
      await settle(page);
      await input.press("Enter");
      await expect(input).toBeHidden();
      await expect(
        canvas.getByRole("button", { name: HEADING_FIELD, exact: true }),
      ).toHaveText(text);
    };

    /** A section from the library dialog the canvas's "+" opened. */
    const addFromLibrary = async (name: string) => {
      await expect(library).toBeVisible();
      await library
        .getByRole("searchbox", { name: "Szukaj układu" })
        .fill(name);
      await library
        .getByRole("button", { name: `Dodaj: ${name}`, exact: true })
        .click();
      await expect(library).toBeHidden();
    };

    const save = async () => {
      const saved = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/api/v1/sites/pages/${pageId}/draft/`) &&
          response.request().method() === "PUT",
      );
      await studio.getByRole("button", { name: "Zapisz stronę" }).click();
      expect([200, 201]).toContain((await saved).status());
    };

    const closeStudio = async () => {
      await studio.getByRole("button", { name: "Wróć do podstron" }).click();
      // A saved page leaves without the "unsaved changes" question.
      await expect(studio).toBeHidden();
    };

    const publish = async (sequence: number) => {
      await page.goto("/panel/sites/publication");
      await page.getByRole("button", { name: "Opublikuj zmiany" }).click();
      await expect(
        page.getByText(`Opublikowano sekwencję ${sequence}.`),
      ).toBeVisible();
    };

    await test.step("logs in and creates the site through onboarding", async () => {
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

      await expect(
        page.getByRole("heading", { name: "Wybierz adres swojej strony" }),
      ).toBeVisible();
      await page.getByLabel("Preferowany adres").fill(SUBDOMAIN);
      await page
        .getByRole("button", { name: "Sprawdź adres i przejdź dalej" })
        .click();
      await expect(
        page.getByRole("heading", { name: "Dodaj podstawowe dane" }),
      ).toBeVisible();
      await page.getByLabel("Nazwa widoczna dla klientów").fill(SITE_NAME);
      await page
        .getByRole("button", { name: "Przejdź do podsumowania" })
        .click();
      await expect(
        page.getByRole("heading", { name: "Sprawdź i utwórz stronę" }),
      ).toBeVisible();
      // The address the review promises is the one the site answers under.
      const promised = page.getByText(new RegExp(`^${SUBDOMAIN}\\.`));
      await expect(promised).toBeVisible();
      hostname = (await promised.textContent())!.trim();
      await page.getByRole("button", { name: "Utwórz moją stronę" }).click();
      await expect(page.getByText(SITE_NAME, { exact: true })).toBeVisible();
      await expect(page.getByText("Jeszcze nieopublikowana")).toBeVisible();
    });

    await test.step("adds a page and fills it from a whole-page template", async () => {
      await page.getByRole("button", { name: "Dodaj podstronę" }).click();
      const create = page.getByRole("dialog", { name: "Dodaj podstronę" });
      await create.locator("#page-name").fill(PAGE_NAME);
      await expect(create.locator("#page-key")).toHaveValue(PAGE_SLUG);
      await create.getByRole("button", { name: "Dodaj podstronę" }).click();
      // The editor opens on the new page right away.
      await expect(studio).toBeVisible();
      const sites = await api<{ items: { id: string }[] }>(
        "GET",
        "/api/v1/sites/",
      );
      const pages = await api<{ items: { id: string; key: string }[] }>(
        "GET",
        `/api/v1/sites/${sites.items[0].id}/pages/`,
      );
      pageId = pages.items.find((item) => item.key === PAGE_SLUG)!.id;

      await expect(studio.getByText("Zacznij od szablonu")).toBeVisible();
      await studio
        .getByRole("button", { name: `Użyj szablonu ${TEMPLATE}` })
        .click();
      // The import copies the template's photo into the library first.
      await expect(sections).toHaveCount(7, { timeout: 90_000 });
      await expect(outline).toHaveText([
        "1. Baner powitalny",
        "2. Tekst",
        "3. Tekst",
        "4. Oferta",
        "5. Tekst",
        "6. Pytania i odpowiedzi",
        "7. Formularz kontaktowy",
      ]);
      // A new page has no history to go back to.
      await expect(undo).toBeDisabled();
    });

    await test.step("sets the page's address, title and description", async () => {
      await studio.getByRole("button", { name: "Ustawienia strony" }).click();
      const metadata = page.getByRole("dialog", {
        name: "Locale i metadane SEO",
      });
      await expect(metadata.getByLabel("Slug", { exact: true })).toHaveValue(
        PAGE_SLUG,
      );
      await metadata
        .getByLabel("Tytuł strony", { exact: true })
        .fill(`${PAGE_NAME} e2e`);
      await metadata
        .getByLabel("Opis meta", { exact: true })
        .fill("Syntetyczna strona testu edytora wizualnego.");
      const saved = page.waitForResponse(
        (response) =>
          response
            .url()
            .endsWith(`/api/v1/sites/pages/${pageId}/translations/pl/`) &&
          response.request().method() === "PUT",
      );
      await metadata.getByRole("button", { name: "Zapisz metadane" }).click();
      expect((await saved).ok()).toBe(true);
      await metadata.getByRole("button", { name: "Zamknij" }).click();
      await expect(metadata).toBeHidden();
    });

    await test.step("edits the selected section's heading on the canvas", async () => {
      await canvas
        .getByRole("button", {
          name: "Edytuj sekcję 1: Baner powitalny",
          exact: true,
        })
        .click();
      await expect(
        canvas.getByRole("button", {
          name: "Edytuj sekcję 1: Baner powitalny",
        }),
      ).toHaveAttribute("aria-pressed", "true");
      await editHeading(FIRST_HEADING);
      await expect(undo).toBeEnabled();
    });

    await test.step("moves a section up with the keyboard on its handle", async () => {
      await canvas
        .getByRole("button", { name: "Przenieś sekcję 4", exact: true })
        .focus();
      await settle(page);
      await page.keyboard.press("ArrowUp");
      await expect(outline).toHaveText([
        "1. Baner powitalny",
        "2. Tekst",
        "3. Oferta",
        "4. Tekst",
        "5. Tekst",
        "6. Pytania i odpowiedzi",
        "7. Formularz kontaktowy",
      ]);
      await expect(
        page.getByText("Sekcja przeniesiona na pozycję 3 z 7."),
      ).toBeAttached();
      // The moved section keeps the focus and the selection.
      await expect(
        canvas.getByRole("button", { name: "Przenieś sekcję 3", exact: true }),
      ).toBeFocused();
      await expect(
        canvas.getByRole("button", { name: "Edytuj sekcję 3: Oferta" }),
      ).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("inserts sections above the first and at the end with the canvas's +", async () => {
      await canvas
        .getByRole("button", { name: "Dodaj sekcję przed sekcją 1" })
        .click();
      await addFromLibrary("Klasyczne FAQ");
      await expect(outline).toHaveText([
        "1. Pytania i odpowiedzi",
        "2. Baner powitalny",
        "3. Tekst",
        "4. Oferta",
        "5. Tekst",
        "6. Tekst",
        "7. Pytania i odpowiedzi",
        "8. Formularz kontaktowy",
      ]);
      await expect(
        canvas.getByRole("button", {
          name: "Edytuj sekcję 1: Pytania i odpowiedzi",
        }),
      ).toHaveAttribute("aria-pressed", "true");

      await canvas
        .getByRole("button", { name: "Dodaj sekcję na końcu strony" })
        .click();
      await addFromLibrary("Cienka linia");
      await expect(sections).toHaveCount(9);
      await expect(outline.last()).toHaveText("9. Separator");
      await expect(
        canvas.getByRole("button", { name: "Edytuj sekcję 9: Separator" }),
      ).toHaveAttribute("aria-pressed", "true");
      await expect(redo).toBeDisabled();
    });

    await test.step("Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y work from the canvas", async () => {
      await canvas.focus();
      await settle(page);
      const step = async (keys: string, undone: boolean) => {
        await page.keyboard.press(keys);
        if (undone) {
          await expect(sections).toHaveCount(8);
          await expect(outline.last()).toHaveText("8. Formularz kontaktowy");
          await expect(redo).toBeEnabled();
        } else {
          await expect(sections).toHaveCount(9);
          await expect(outline.last()).toHaveText("9. Separator");
          await expect(redo).toBeDisabled();
        }
        // Only the last insert moves: the one above, the move and the
        // heading stay.
        await expect(undo).toBeEnabled();
        await expect(outline.first()).toHaveText("1. Pytania i odpowiedzi");
        await expect(canvas).toBeFocused();
        await settle(page);
      };
      await step("Control+z", true);
      await step("Control+Shift+z", false);
      await step("Control+z", true);
      await step("Control+y", false);
    });

    await test.step("switches the canvas to a phone and back", async () => {
      const viewports = studio.getByRole("group", {
        name: "Rozmiar podglądu",
      });
      await expect(canvas).toHaveAttribute("data-viewport", "desktop");
      await viewports.getByRole("button", { name: "Telefon" }).click();
      await expect(canvas).toHaveAttribute("data-viewport", "mobile");
      await expect(
        viewports.getByRole("button", { name: "Telefon" }),
      ).toHaveAttribute("aria-pressed", "true");
      expect((await canvas.boundingBox())?.width).toBeLessThanOrEqual(390);
      await viewports.getByRole("button", { name: "Komputer" }).click();
      await expect(canvas).toHaveAttribute("data-viewport", "desktop");
    });

    await test.step("'Zmień zdjęcie' on the selected section opens its photo field", async () => {
      const change = canvas.getByRole("button", { name: /^Zmień zdjęcie/ });
      // Only the selected section offers it: the separator has no photo.
      await expect(change).toHaveCount(0);
      await canvas
        .getByRole("button", {
          name: "Edytuj sekcję 2: Baner powitalny",
          exact: true,
        })
        .click();
      await expect(change).toHaveCount(1);
      await expect(change).toHaveAccessibleName(`Zmień zdjęcie: ${PHOTO_ALT}`);
      await change.click();
      const photo = inspector.getByLabel("Obraz", { exact: true });
      await expect(photo).toBeFocused();
      await expect(photo).toHaveValue(/^[0-9a-f-]{36}$/);
    });

    await test.step("saves the page; the draft holds the order and the heading", async () => {
      await save();
      await expect(undo).toBeDisabled();
      const draft = await api<Draft>(
        "GET",
        `/api/v1/sites/pages/${pageId}/draft/`,
      );
      expect(draft.blocks.map((block) => block.block_type)).toEqual([
        "core.faq",
        "core.hero",
        "core.rich_text",
        "core.feature_list",
        "core.rich_text",
        "core.rich_text",
        "core.faq",
        "core.contact_form",
        "core.separator",
      ]);
      expect(draft.blocks[1].data.title).toBe(FIRST_HEADING);
      expect(draft.blocks[3].data.title).toBe("Jak przebiega wizyta");
      expect(draft.blocks[1].data.image).toMatchObject({ alt: PHOTO_ALT });
      await closeStudio();
    });

    // The published site under its own host, through the stack's Caddy,
    // set up like site-catalog.spec.ts.
    let browser: Browser | undefined;
    let visitors: BrowserContext;
    const expectPublished = async (shown: string, hidden?: string) => {
      const visitor = await visitors.newPage();
      visitor.on("pageerror", (error) => publicErrors.push(error.message));
      try {
        const response = await visitor.goto(`http://${hostname}/${PAGE_SLUG}/`);
        expect(response?.status()).toBe(200);
        // Served at the canonical address itself: `goto` follows redirects,
        // so a 308 in front of the 200 shows only here (ADR-071).
        expect(response?.request().redirectedFrom()).toBeNull();
        // The other spelling is one 308 away, not a second copy of the page.
        const other = await visitor.goto(`http://${hostname}/${PAGE_SLUG}`);
        expect(other?.url()).toBe(`http://${hostname}/${PAGE_SLUG}/`);
        const hop = other?.request().redirectedFrom();
        expect(hop?.url()).toBe(`http://${hostname}/${PAGE_SLUG}`);
        expect(hop?.redirectedFrom()).toBeNull();
        await expect(
          visitor.getByRole("heading", { name: shown, exact: true }),
        ).toBeVisible();
        if (hidden) await expect(visitor.getByText(hidden)).toHaveCount(0);
      } finally {
        await visitor.close();
      }
    };

    try {
      await test.step("publishes; the site shows the edited heading", async () => {
        await publish(1);
        const sites = await api<{ items: { id: string }[] }>(
          "GET",
          "/api/v1/sites/",
        );
        const domains = await api<{
          items: { hostname: string; is_canonical: boolean }[];
        }>("GET", `/api/v1/sites/${sites.items[0].id}/domains/`);
        expect(
          domains.items.find((domain) => domain.is_canonical)?.hostname,
        ).toBe(hostname);
        // Full Chromium (not the headless shell) honours the secure-origin
        // flag, so the page behaves as over https.
        browser = await chromium.launch({
          channel: "chromium",
          args: [
            `--host-resolver-rules=MAP ${hostname} ${new URL(origin).host}`,
            `--unsafely-treat-insecure-origin-as-secure=http://${hostname}`,
          ],
        });
        visitors = await browser.newContext({ locale: "pl-PL" });
        // Only the site's own requests: on a font CDN the header would force
        // a CORS preflight.
        await visitors.route(`http://${hostname}/**`, (route) =>
          route.continue({
            headers: {
              ...route.request().headers(),
              "x-forwarded-proto": "https",
            },
          }),
        );
        await expectPublished(FIRST_HEADING);
      });

      await test.step("changes the heading again and publishes a second time", async () => {
        await page.goto(`/panel/sites/pages/${pageId}`);
        await expect(studio).toBeVisible();
        await expect(sections).toHaveCount(9);
        await canvas
          .getByRole("button", {
            name: "Edytuj sekcję 2: Baner powitalny",
            exact: true,
          })
          .click();
        await editHeading(SECOND_HEADING);
        await save();
        await closeStudio();
        await publish(2);
        await expectPublished(SECOND_HEADING, FIRST_HEADING);
      });

      await test.step("rolls back to the first publication without losing the draft", async () => {
        const history = page.locator("article");
        // Restoring sits in the row's „…” and says what it does (UX-044).
        await page
          .getByRole("button", { name: "Działania dla publikacji #1" })
          .click();
        await page
          .getByRole("menuitem", { name: "Przywróć jako nową publikację" })
          .click();
        await expect(page.getByText("Opublikowano sekwencję 3.")).toBeVisible();
        const restored = history.filter({
          has: page.getByText("Publikacja #3", { exact: true }),
        });
        await expect(
          restored.getByText("Bieżąca", { exact: true }),
        ).toBeVisible();
        await expect(
          restored.getByText("Rollback", { exact: true }),
        ).toBeVisible();
        await expectPublished(FIRST_HEADING, SECOND_HEADING);
        const draft = await api<Draft>(
          "GET",
          `/api/v1/sites/pages/${pageId}/draft/`,
        );
        expect(draft.blocks[1].data.title).toBe(SECOND_HEADING);
      });
    } finally {
      await browser?.close();
    }

    expect(panelErrors).toEqual([]);
    expect(publicErrors).toEqual([]);
  });
});
