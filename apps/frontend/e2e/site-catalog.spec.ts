import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium, expect, test } from "@playwright/test";
import type {
  PageTemplate,
  SectionTemplate,
  SiteBlock,
} from "@saas-core/site-blocks";

// F4-P0a: a section template or a page recipe enters the catalogue only after
// it has been published on a running stack and looked at in every page style
// and width. How and when to run this: e2e/site-catalog.md.

// ponytail: required, not imported. The package imports its JSON contracts
// without `with { type: "json" }`, which Node's ESM loader refuses; Playwright
// compiles a required file to CommonJS, where JSON loads as is.
const {
  applySampleMedia,
  corePageTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  isRetiredPageTemplate,
  offeredSectionTemplates,
  sectionTemplateBlock,
} = createRequire(import.meta.url)(
  "@saas-core/site-blocks",
) as typeof import("@saas-core/site-blocks");

const env = process.env;
const here = path.dirname(fileURLToPath(import.meta.url));
const contract = (file: string) =>
  JSON.parse(
    readFileSync(
      path.join(here, "../../../packages/contracts/site-blocks", file),
      "utf8",
    ),
  );

const WIDTHS = [320, 390, 768, 1024, 1440];
const FULL_PAGE_WIDTH = 3440;
const BLOCKS_PER_PAGE = 20;
const PRIMARY_ACTION =
  ".site-section__action:not(.site-section__action--secondary)";
const styles: string[] =
  env.SITE_CATALOG_STYLES?.split(",").map((style) => style.trim()) ??
  contract("page-presentation.v2.schema.json").properties.style.enum;
// The published site is reached through the stack's Caddy under its own host.
const proxy = env.SITE_CATALOG_PROXY ?? "127.0.0.1:8080";

const runId = randomUUID().replaceAll("-", "").slice(0, 10);
const slug = env.SITE_CATALOG_SLUG ?? `w6-e2e-catalog-${runId}`;
// Also the environment of site-catalog-run.sh, which owns the fixture.
const account = {
  SITE_CATALOG_SLUG: slug,
  SITE_CATALOG_EMAIL: env.SITE_CATALOG_EMAIL ?? `${slug}@example.test`,
  SITE_CATALOG_PASSWORD:
    env.SITE_CATALOG_PASSWORD ?? `W6-E2E-${randomUUID()}-aA1!`,
};
// Ready credentials mean the caller (the wrapper) prepares and cleans up.
const ownFixture = env.SITE_CATALOG_EMAIL === undefined;

const inV6 = new Set(
  (contract("section-templates.v6.json").templates as SectionTemplate[]).map(
    (template) => `${template.id}@${template.version}`,
  ),
);
const templates = offeredSectionTemplates().filter(
  (template) =>
    env.SITE_CATALOG_ALL === "1" ||
    !inV6.has(`${template.id}@${template.version}`),
);
const recipes =
  env.SITE_CATALOG_PAGES === "1"
    ? corePageTemplates().filter((recipe) => !isRetiredPageTemplate(recipe.id))
    : [];

interface Source {
  name: string;
  title: string;
  templates: readonly SectionTemplate[];
  recipe?: PageTemplate;
  widths: number[];
}
const sources: Source[] = [
  ...Array.from(
    { length: Math.ceil(templates.length / BLOCKS_PER_PAGE) },
    (_, index) => ({
      name: `sections-${index + 1}`,
      title: `Sekcje, strona ${index + 1}`,
      templates: templates.slice(
        index * BLOCKS_PER_PAGE,
        (index + 1) * BLOCKS_PER_PAGE,
      ),
      widths: WIDTHS,
    }),
  ),
  ...recipes.map((recipe) => ({
    name: recipe.id.replace(/^core\./, "").replaceAll("_", "-"),
    title: `${recipe.id}@${recipe.version} · ${recipe.labels.pl.name}`,
    templates: [],
    recipe,
    widths:
      recipe.pagePresentation?.width === "full"
        ? [...WIDTHS, FULL_PAGE_WIDTH]
        : WIDTHS,
  })),
];

interface Draft {
  version: number;
  blocks: SiteBlock[];
  media_asset_ids: string[];
  page_presentation: Record<string, unknown> | null;
}

function fixture(action: "prepare" | "cleanup") {
  execFileSync("bash", [path.join(here, "site-catalog-run.sh"), action], {
    env: { ...env, ...account },
    stdio: "inherit",
  });
}

test.describe("Site catalogue screenshots (F4-P0a)", () => {
  test.skip(
    env.SITE_CATALOG_HARNESS !== "1",
    "Publishes a page per template chunk and page style on a live stack; run it with SITE_CATALOG_HARNESS=1 (e2e/site-catalog.md).",
  );
  test.beforeAll(() => {
    if (ownFixture) fixture("prepare");
  });
  test.afterAll(() => {
    if (ownFixture) fixture("cleanup");
  });

  test("publishes templates and recipes in every page style and width", async ({
    page,
  }, testInfo) => {
    test.setTimeout(0);
    page.setDefaultTimeout(60_000);
    const origin = new URL(String(testInfo.project.use.baseURL)).origin;
    const out = path.join(testInfo.project.outputDir, "site-catalog");
    const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
    const failures: string[] = [];
    const taken = new Set<string>();

    const api = async <T>(method: string, url: string, data?: unknown) => {
      const csrf = (await page.context().cookies()).find(
        (cookie) => cookie.name === "csrftoken",
      )?.value;
      const response = await page.request.fetch(url, {
        method,
        data,
        timeout: 180_000,
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

    const site = await api<{ id: string }>("POST", "/api/v1/sites/", {
      name: "Przegląd katalogu",
      slug: account.SITE_CATALOG_SLUG,
      default_locale: "pl",
    });
    const photos = new Map<string, string>();
    const photo = async (id: string) => {
      if (!photos.has(id))
        photos.set(
          id,
          (
            await api<{ asset_id: string }>(
              "POST",
              `/api/v1/sites/template-media/${id}/materialize/`,
            )
          ).asset_id,
        );
      return photos.get(id)!;
    };

    for (const source of sources) {
      const seeded: SiteBlock[] = [];
      for (const template of source.templates) {
        const block = sectionTemplateBlock(template, "pl", registry);
        seeded.push(
          template.sampleMedia
            ? applySampleMedia(
                block,
                template,
                await photo(template.sampleMedia.id),
                "pl",
              )
            : block,
        );
      }
      for (const style of styles) {
        const key = `${source.name}-${style}`;
        const created = await api<{ id: string }>(
          "POST",
          `/api/v1/sites/${site.id}/pages/`,
          { name: key, key },
        );
        // A recipe goes through the panel's import, which binds its photos.
        const draft: Draft = source.recipe
          ? await api<Draft>(
              "POST",
              `/api/v1/sites/pages/${created.id}/template-import/`,
              {
                expected_version: 0,
                template_id: source.recipe.id,
                template_version: source.recipe.version,
                locale: "pl",
              },
            )
          : {
              version: 0,
              blocks: seeded,
              media_asset_ids: [],
              page_presentation: null,
            };
        await api("PUT", `/api/v1/sites/pages/${created.id}/draft/`, {
          expected_version: draft.version,
          blocks: draft.blocks,
          media_asset_ids: draft.media_asset_ids,
          page_presentation: {
            ...draft.page_presentation,
            schemaVersion: 2,
            style,
          },
        });
        await api("PUT", `/api/v1/sites/pages/${created.id}/translations/pl/`, {
          expected_version: 0,
          slug: key,
          title: `${source.title} · ${style}`,
          description: "Syntetyczna strona przeglądu katalogu sekcji.",
          social_title: "",
          social_description: "",
        });
      }
    }
    await api("POST", `/api/v1/sites/${site.id}/publications/`, {});
    const domains = await api<{
      items: { hostname: string; is_canonical: boolean }[];
    }>("GET", `/api/v1/sites/${site.id}/domains/`);
    const host = domains.items.find((domain) => domain.is_canonical)!.hostname;

    // Full Chromium (not the headless shell) honours the secure-origin flag,
    // so the page behaves as over https (crypto.randomUUID and the like).
    const browser = await chromium.launch({
      channel: "chromium",
      args: [
        `--host-resolver-rules=MAP ${host} ${proxy}`,
        `--unsafely-treat-insecure-origin-as-secure=http://${host}`,
      ],
    });
    try {
      const context = await browser.newContext({ locale: "pl-PL" });
      // Only the site's own requests: on a font CDN the header would force a
      // CORS preflight.
      await context.route(`http://${host}/**`, (route) =>
        route.continue({
          headers: {
            ...route.request().headers(),
            "x-forwarded-proto": "https",
          },
        }),
      );
      for (const source of sources)
        for (const style of styles)
          for (const width of source.widths) {
            const label = `${style} / ${source.name} @ ${width}`;
            // A fresh tab each time: a renderer that crashes (a loaded host
            // does that) costs one shot, not the rest of the run.
            const visitor = await context.newPage();
            visitor.setDefaultTimeout(60_000);
            const errors: string[] = [];
            visitor.on("pageerror", (error) => errors.push(error.message));
            try {
              await visitor.setViewportSize({
                width,
                height: width < 768 ? 844 : 900,
              });
              await expect(async () => {
                const response = await visitor.goto(
                  `http://${host}/${source.name}-${style}/`,
                );
                expect(response?.status()).toBe(200);
              }).toPass({ timeout: 120_000 });
              // Lazy images load only near the viewport; a full-page shot
              // would show them empty.
              await visitor.evaluate(async () => {
                for (let y = 0; y < document.body.scrollHeight; y += 400) {
                  window.scrollTo(0, y);
                  await new Promise((resolve) => setTimeout(resolve, 50));
                }
                window.scrollTo(0, 0);
                await document.fonts.ready;
              });
              await visitor.waitForFunction(() =>
                Array.from(document.images).every((image) => image.complete),
              );
              const problems = await visitor.evaluate((primary) => {
                const found: string[] = [];
                const { scrollWidth } = document.documentElement;
                if (scrollWidth > window.innerWidth + 1)
                  found.push(
                    `horizontal overflow: scrollWidth ${scrollWidth} > ${window.innerWidth}`,
                  );
                for (const link of document.querySelectorAll('a[href^="#"]')) {
                  const href = link.getAttribute("href")!;
                  if (
                    !document.getElementById(decodeURIComponent(href.slice(1)))
                  )
                    found.push(`anchor ${href} has no target`);
                }
                if (document.body.innerText.includes("[object Object]"))
                  found.push('text "[object Object]"');
                for (const image of document.querySelectorAll("img:not([alt])"))
                  found.push(`image without alt: ${image.getAttribute("src")}`);
                document
                  .querySelectorAll("main > *")
                  .forEach((section, index) => {
                    const count = section.querySelectorAll(primary).length;
                    if (count > 1)
                      found.push(
                        `section ${index + 1}: ${count} primary actions`,
                      );
                  });
                return found;
              }, PRIMARY_ACTION);
              for (const problem of [
                ...problems,
                ...errors.map((error) => `pageerror: ${error}`),
              ])
                failures.push(`${label}: ${problem}`);

              const shot = `${style}/${source.name}-${width}.png`;
              await visitor.screenshot({
                path: path.join(out, shot),
                fullPage: true,
              });
              taken.add(shot);
              const sections = visitor.locator("main > *");
              if (
                source.templates.length > 0 &&
                (await sections.count()) !== source.templates.length
              ) {
                failures.push(
                  `${label}: ${await sections.count()} sections rendered for ${source.templates.length} templates`,
                );
                continue;
              }
              for (const [index, template] of source.templates.entries()) {
                const file = `${style}/${source.name}/${template.id}-${width}.png`;
                await sections
                  .nth(index)
                  .screenshot({ path: path.join(out, file) });
                taken.add(file);
              }
            } catch (error) {
              failures.push(
                `${label}: ${String(error instanceof Error ? error.message : error).split("\n")[0]}`,
              );
            } finally {
              await visitor.close();
            }
          }
    } finally {
      await browser.close();
    }

    mkdirSync(out, { recursive: true });
    writeFileSync(
      path.join(out, "index.html"),
      reviewPage(failures, taken, `${origin} → http://${host}`),
    );
    console.log(`Review page: ${path.join(out, "index.html")}`);
    expect(failures, `see ${path.join(out, "index.html")}`).toEqual([]);
  });
});

function reviewPage(
  failures: readonly string[],
  taken: ReadonlySet<string>,
  target: string,
) {
  const escape = (text: string) =>
    text.replace(/[&<>"]/g, (char) => `&#${char.charCodeAt(0)};`);
  const figure = (file: string, width: number) =>
    `<figure style="width:${Math.round(width / 3)}px">${
      taken.has(file)
        ? `<a href="${escape(file)}"><img src="${escape(file)}" alt="${width}px" loading="lazy"></a>`
        : "<p>brak zrzutu</p>"
    }<figcaption>${width}px</figcaption></figure>`;
  const rows = (
    widths: number[],
    file: (style: string, width: number) => string,
  ) =>
    styles
      .map(
        (style) =>
          `<h4>${escape(style)}</h4><div class="row">${widths
            .map((width) => figure(file(style, width), width))
            .join("")}</div>`,
      )
      .join("");
  const sections = sources.flatMap((source) =>
    source.templates.map(
      (template) =>
        `<section><h3>${escape(`${template.id}@${template.version}`)}</h3><p>${escape(
          [
            `układ ${template.layout}`,
            `etap ${template.conversion?.stage ?? "—"}`,
            template.conversion?.primaryAction ? "główna akcja" : "",
            template.labels.pl.name,
          ]
            .filter(Boolean)
            .join(" · "),
        )}</p>${rows(
          source.widths,
          (style, width) =>
            `${style}/${source.name}/${template.id}-${width}.png`,
        )}</section>`,
    ),
  );
  const pages = sources.map(
    (source) =>
      `<section><h3>${escape(source.title)}</h3>${rows(
        source.widths,
        (style, width) => `${style}/${source.name}-${width}.png`,
      )}</section>`,
  );
  return `<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>Przegląd katalogu sekcji</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;margin:24px;color:#111;background:#fff}
.row{display:flex;gap:16px;overflow-x:auto;align-items:flex-start;padding-bottom:8px}
figure{margin:0;flex:none}img{width:100%;border:1px solid #ccc}
figcaption{color:#555}.failures li{color:#a00}section{border-top:1px solid #ddd;margin-top:24px}
</style></head><body>
<h1>Przegląd katalogu sekcji</h1>
<p>${escape(target)} · style: ${escape(styles.join(", "))} · ${new Date().toISOString()}</p>
<h2>Problemy (${failures.length})</h2>
${failures.length ? `<ul class="failures">${failures.map((failure) => `<li>${escape(failure)}</li>`).join("")}</ul>` : "<p>Brak problemów.</p>"}
<h2>Szablony sekcji (${templates.length})</h2>
${sections.join("\n")}
<h2>Strony (${sources.length})</h2>
${pages.join("\n")}
</body></html>
`;
}
