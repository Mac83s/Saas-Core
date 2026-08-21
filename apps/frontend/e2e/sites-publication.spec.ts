import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, test, type Page, type Route } from "@playwright/test";

const runId = randomUUID().replaceAll("-", "").slice(0, 12);
const email = `w6-e2e-${runId}@example.test`;
const organizationSlug = `w6-e2e-${runId}`;
const password = `W6-E2E-${randomUUID()}-aA1!`;

test.describe("W9.5 Sites onboarding and publication workspace", () => {
  test.beforeAll(() => fixture("prepare"));
  test.afterAll(() => fixture("cleanup"));

  test("creates content, previews, publishes and rolls back without losing the draft", async ({
    page,
  }) => {
    const siteName = `Site ${runId}`;
    await installSitesApiMock(page);
    await page.goto("/login?next=/panel/sites");
    await page.getByLabel("E-mail").fill(email);
    await page.getByLabel("Hasło").fill(password);
    await page.getByRole("button", { name: "Zaloguj się" }).click();
    await expect(page).toHaveURL(/\/panel\/sites$/);
    await expect(
      page.getByRole("heading", { name: "Treść strony" }),
    ).toBeVisible();

    await page.getByLabel("Preferowany adres").fill(`site-${runId}`);
    await page
      .getByRole("button", { name: "Sprawdź adres i przejdź dalej" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Dodaj podstawowe dane" }),
    ).toBeVisible();
    await page.getByLabel("Nazwa widoczna dla klientów").fill(siteName);
    await page.getByRole("button", { name: "Przejdź do podsumowania" }).click();
    await expect(
      page.getByRole("heading", { name: "Sprawdź i utwórz stronę" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Utwórz moją stronę" }).click();
    await expect(page.getByText(siteName, { exact: true })).toBeVisible();
    await page.getByLabel("Własna domena").fill(`www-${runId}.example.test`);
    await page.getByRole("button", { name: "Dodaj domenę" }).click();
    await expect(
      page.getByText(`www-${runId}.example.test`, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/_saas-core\.www-/)).toBeVisible();
    await page.getByRole("button", { name: "Sprawdź DNS" }).click();
    await expect(
      page.getByText("zweryfikowana", { exact: true }),
    ).toBeVisible();

    await page.locator("#page-name").fill("Start");
    await page.locator("#page-key").fill("home");
    await page.getByRole("button", { name: "Dodaj podstronę" }).click();
    await expect(
      page.getByText("Kontrolowane bloki treści", { exact: true }),
    ).toBeVisible();

    const contentForm = page
      .getByRole("button", { name: "Zapisz nową wersję draftu" })
      .locator("xpath=ancestor::form");
    await contentForm.getByRole("combobox", { name: "Typ bloku" }).click();
    await page.getByRole("option", { name: "Hero", exact: true }).click();
    await contentForm.getByRole("button", { name: "Dodaj" }).first().click();
    await contentForm.getByLabel("Nagłówek").fill("Pierwsza publikacja");
    await contentForm.getByLabel("Treść").fill("Treść kontrolowanego bloku");
    await contentForm
      .getByRole("button", { name: "Zapisz nową wersję draftu" })
      .click();
    await expect(
      contentForm.getByText("Wersja 1", { exact: true }),
    ).toBeVisible();

    const metadataForm = page
      .getByRole("button", { name: "Zapisz metadane" })
      .locator("xpath=ancestor::form");
    await metadataForm.getByLabel("Tytuł strony").fill("Strona główna");
    await metadataForm.getByLabel("Opis meta").fill("Opis strony głównej");
    await metadataForm.getByRole("button", { name: "Zapisz metadane" }).click();
    await expect(
      metadataForm.getByText("Wersja 1", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Gotowy do publikacji", { exact: true }),
    ).toBeVisible();

    await contentForm
      .getByRole("button", { name: "Chroniony podgląd" })
      .click();
    await expect(page.getByTestId("draft-preview")).toContainText(
      "Pierwsza publikacja",
    );

    await page.getByRole("button", { name: "Opublikuj snapshot" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Opublikowano sekwencję 1",
    );
    await expect(
      page.getByText("Publikacja #1", { exact: true }),
    ).toBeVisible();

    await contentForm.getByLabel("Nagłówek").fill("Nowszy niezależny draft");
    await contentForm
      .getByRole("button", { name: "Zapisz nową wersję draftu" })
      .click();
    await expect(
      contentForm.getByText("Wersja 2", { exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByText("Wersja", { exact: true })
        .locator("xpath=following-sibling::p"),
    ).toHaveText("2");
    const secondPublish = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        new URL(request.url()).pathname ===
          "/api/v1/sites/019ff20d-a000-7000-8000-000000000010/publications/",
    );
    await page.getByRole("button", { name: "Opublikuj snapshot" }).click();
    await secondPublish;
    await expect(page.getByRole("status")).toContainText(
      "Opublikowano sekwencję 2",
    );
    await expect(
      page.getByText("Publikacja #2", { exact: true }),
    ).toBeVisible();

    const firstPublication = page
      .getByText("Publikacja #1", { exact: true })
      .locator("xpath=ancestor::article");
    const restoreButton = firstPublication.getByRole("button", {
      name: "Przywróć jako nową publikację",
    });
    await expect(restoreButton).toBeEnabled();
    const rollback = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith(
          "/publications/019ff20d-a000-7000-8002-000000000001/rollback/",
        ) &&
        response.status() === 201,
    );
    await restoreButton.click();
    await rollback;
    await expect(page.getByRole("status")).toContainText(
      "Opublikowano sekwencję 3",
    );
    await expect(
      page.getByText("Publikacja #3", { exact: true }),
    ).toBeVisible();
    await expect(contentForm.getByLabel("Nagłówek")).toHaveValue(
      "Nowszy niezależny draft",
    );
  });
});

function fixture(action: "prepare" | "cleanup") {
  const args = ["compose", "exec", "-T"];
  if (action === "prepare") {
    args.push("-e", `SITES_E2E_PASSWORD=${password}`);
  }
  args.push(
    "backend",
    "python",
    "manage.py",
    "sites_e2e_fixture",
    action,
    "--email",
    email,
    "--slug",
    organizationSlug,
  );
  execFileSync("docker", args, { cwd: "../..", stdio: "inherit" });
}

async function installSitesApiMock(page: Page) {
  const state = createMockState();
  await page.route("**/api/v1/media/**", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route("**/api/v1/sites/**", (route) =>
    handleSitesRoute(route, state),
  );
}

type MockState = ReturnType<typeof createMockState>;

function createMockState() {
  return {
    site: null as null | Record<string, unknown>,
    onboarding: {
      id: null as string | null,
      version: 0,
      step: "address",
      name: "",
      subdomain_label: "",
      default_locale: "pl",
      platform_domain: "sites.core.localhost",
      hostname: "",
      site_id: null as string | null,
      updated_at: null as string | null,
    },
    page: null as null | Record<string, unknown>,
    draft: {
      page_id: "019ff20d-a000-7000-8000-000000000020",
      version: 0,
      draft_id: null as string | null,
      content_hash: null as string | null,
      created_at: null as string | null,
      blocks: [] as Record<string, unknown>[],
      media_asset_ids: [] as string[],
    },
    translation: null as null | Record<string, unknown>,
    publications: [] as Record<string, unknown>[],
    domains: [] as Record<string, unknown>[],
  };
}

async function handleSitesRoute(route: Route, state: MockState) {
  const request = route.request();
  const method = request.method();
  const path = new URL(request.url()).pathname;
  const now = "2026-08-11T12:00:00Z";
  const siteId = "019ff20d-a000-7000-8000-000000000010";
  const pageId = "019ff20d-a000-7000-8000-000000000020";

  if (path === "/api/v1/sites/subdomain-availability/" && method === "GET") {
    const label = new URL(request.url()).searchParams.get("label") ?? "";
    const normalizedLabel = label.toLowerCase();
    return fulfill(route, {
      requested_label: label,
      normalized_label: normalizedLabel,
      hostname: `${normalizedLabel}.sites.core.localhost`,
      available: true,
      reason: "available",
      suggestion: "",
    });
  }
  if (path === "/api/v1/sites/onboarding/" && method === "GET") {
    return fulfill(route, state.onboarding);
  }
  if (path === "/api/v1/sites/onboarding/" && method === "PUT") {
    const body = request.postDataJSON() as {
      version: number;
      step: string;
      name: string;
      subdomain_label: string;
      default_locale: string;
    };
    state.onboarding = {
      ...state.onboarding,
      ...body,
      id: "019ff20d-a000-7000-8000-000000000011",
      version: body.version + 1,
      hostname: body.subdomain_label
        ? `${body.subdomain_label}.sites.core.localhost`
        : "",
      updated_at: now,
    };
    return fulfill(route, state.onboarding);
  }
  if (path === "/api/v1/sites/onboarding/complete/" && method === "POST") {
    state.site = {
      id: siteId,
      name: state.onboarding.name,
      slug: state.onboarding.subdomain_label,
      default_locale: state.onboarding.default_locale,
      current_publication_id: null,
      created_at: now,
      updated_at: now,
    };
    state.onboarding.site_id = siteId;
    state.onboarding.step = "completed";
    state.domains = [
      domainRecord({
        id: "019ff20d-a000-7000-8000-000000000040",
        hostname: state.onboarding.hostname,
        kind: "platform",
        status: "verified",
        tls_status: "eligible",
        is_canonical: true,
        siteId,
      }),
    ];
    return fulfill(route, state.site, 201);
  }
  if (path === "/api/v1/sites/" && method === "GET") {
    return fulfill(route, {
      items: state.site ? [state.site] : [],
      next_cursor: null,
    });
  }
  if (path === `/api/v1/sites/${siteId}/domains/` && method === "GET") {
    return fulfill(route, { items: state.domains });
  }
  if (path === `/api/v1/sites/${siteId}/domains/` && method === "POST") {
    const body = request.postDataJSON() as { hostname: string };
    const domain = domainRecord({
      id: "019ff20d-a000-7000-8000-000000000041",
      hostname: body.hostname,
      kind: "custom",
      status: "pending",
      tls_status: "pending",
      is_canonical: false,
      siteId,
    });
    state.domains.push(domain);
    return fulfill(route, domain, 201);
  }
  if (
    path ===
      "/api/v1/sites/domains/019ff20d-a000-7000-8000-000000000041/actions/" &&
    method === "POST"
  ) {
    const domain = state.domains[1];
    if (domain) {
      domain.status = "verified";
      domain.tls_status = "eligible";
    }
    return fulfill(route, domain, 202);
  }
  if (path === `/api/v1/sites/${siteId}/pages/` && method === "GET") {
    return fulfill(route, {
      items: state.page ? [state.page] : [],
      next_cursor: null,
    });
  }
  if (path === `/api/v1/sites/${siteId}/pages/` && method === "POST") {
    const body = request.postDataJSON() as { name: string; key: string };
    state.page = {
      id: pageId,
      site_id: siteId,
      ...body,
      version: 0,
      current_draft_id: null,
      current_draft_hash: null,
      created_at: now,
      updated_at: now,
    };
    return fulfill(route, state.page, 201);
  }
  if (path === `/api/v1/sites/pages/${pageId}/draft/` && method === "GET") {
    return fulfill(route, state.draft);
  }
  if (path === `/api/v1/sites/pages/${pageId}/draft/` && method === "PUT") {
    const body = request.postDataJSON() as {
      blocks: Array<{
        block_type: string;
        schema_version: number;
        data: Record<string, unknown>;
      }>;
      media_asset_ids: string[];
    };
    const version = state.draft.version + 1;
    state.draft = {
      page_id: pageId,
      version,
      draft_id: `019ff20d-a000-7000-8000-${String(30 + version).padStart(12, "0")}`,
      content_hash: String(version).repeat(64),
      created_at: now,
      blocks: body.blocks.map((block, position) => ({
        id: `019ff20d-a000-7000-8001-${String(30 + position).padStart(12, "0")}`,
        position,
        ...block,
      })),
      media_asset_ids: body.media_asset_ids,
    };
    if (state.page) {
      state.page.version = version;
      state.page.current_draft_id = state.draft.draft_id;
      state.page.current_draft_hash = state.draft.content_hash;
    }
    return fulfill(route, state.draft);
  }
  if (
    path.startsWith(`/api/v1/sites/pages/${pageId}/preview/`) &&
    method === "GET"
  ) {
    return fulfill(route, state.draft);
  }
  if (
    path === `/api/v1/sites/pages/${pageId}/translations/` &&
    method === "GET"
  ) {
    return fulfill(route, {
      page_id: pageId,
      default_locale: "pl",
      supported_locales: ["pl", "en"],
      items: state.translation ? [state.translation] : [],
    });
  }
  if (
    path === `/api/v1/sites/pages/${pageId}/translations/pl/` &&
    method === "PUT"
  ) {
    const body = request.postDataJSON() as Record<string, unknown>;
    state.translation = {
      id: "019ff20d-a000-7000-8000-000000000023",
      page_id: pageId,
      site_id: siteId,
      locale: "pl",
      ...body,
      version: 1,
      slug_locked: state.publications.length > 0,
      created_at: now,
      updated_at: now,
    };
    return fulfill(route, state.translation);
  }
  if (path === `/api/v1/sites/${siteId}/localization/` && method === "GET") {
    const ready = state.draft.version > 0 && state.translation !== null;
    return fulfill(route, {
      site_id: siteId,
      default_locale: "pl",
      supported_locales: ["pl", "en"],
      ready_to_publish: ready,
      pages: state.page
        ? [
            {
              page_id: pageId,
              page_key: "home",
              page_name: "Start",
              locales: [localization("pl", ready), localization("en", false)],
              hreflang: ready ? { pl: "/home/" } : {},
              x_default: ready ? "/home/" : null,
            },
          ]
        : [],
    });
  }
  if (path === `/api/v1/sites/${siteId}/publications/` && method === "GET") {
    return fulfill(route, {
      items: [...state.publications].reverse(),
      next_cursor: null,
    });
  }
  if (path === `/api/v1/sites/${siteId}/publications/` && method === "POST") {
    return createPublication(route, state, siteId, email, now, null);
  }
  const rollback = path.match(
    new RegExp(`^/api/v1/sites/${siteId}/publications/([^/]+)/rollback/$`),
  );
  if (rollback && method === "POST") {
    return createPublication(
      route,
      state,
      siteId,
      email,
      now,
      rollback[1] ?? null,
    );
  }
  return route.fulfill({
    status: 501,
    json: { detail: `Unhandled E2E API route: ${method} ${path}` },
  });
}

function domainRecord({
  hostname,
  id,
  is_canonical,
  kind,
  siteId,
  status,
  tls_status,
}: {
  hostname: string;
  id: string;
  is_canonical: boolean;
  kind: "custom" | "platform";
  siteId: string;
  status: string;
  tls_status: string;
}) {
  const custom = kind === "custom";
  return {
    id,
    site_id: siteId,
    hostname,
    kind,
    status,
    tls_status,
    is_canonical,
    verification_name: custom ? `_saas-core.${hostname}` : "",
    verification_token: custom
      ? `saas-core-domain-verification=${id}.test-token`
      : "",
    dns_cname_target: "sites.core.localhost",
    dns_expected_ipv4: [],
    dns_expected_ipv6: [],
    dns_error_code: "",
    last_checked_at: custom ? null : "2026-08-12T08:00:00Z",
    last_verified_at: custom ? null : "2026-08-12T08:00:00Z",
    next_check_at: custom ? "2026-08-12T08:01:00Z" : null,
    tls_last_requested_at: null,
    released_at: null,
    quarantine_until: null,
    created_at: "2026-08-12T08:00:00Z",
  };
}

function createPublication(
  route: Route,
  state: MockState,
  siteId: string,
  authorEmail: string,
  createdAt: string,
  sourcePublicationId: string | null,
) {
  const sequence = state.publications.length + 1;
  const publication = {
    id: `019ff20d-a000-7000-8002-${String(sequence).padStart(12, "0")}`,
    site_id: siteId,
    sequence,
    snapshot_schema_version: 1,
    snapshot_hash: String(sequence).repeat(64),
    source_publication_id: sourcePublicationId,
    created_by: {
      id: "019ff20d-a000-7000-8000-000000000027",
      email: authorEmail,
    },
    created_at: createdAt,
  };
  state.publications.push(publication);
  if (state.site) state.site.current_publication_id = publication.id;
  return fulfill(route, publication, 201);
}

function localization(locale: string, complete: boolean) {
  return {
    locale,
    translation_id: complete ? "019ff20d-a000-7000-8000-000000000023" : null,
    version: complete ? 1 : null,
    slug: complete ? "home" : null,
    path: complete ? "/home/" : null,
    canonical_path: complete ? "/home/" : null,
    title: complete ? "Strona główna" : null,
    description: complete ? "Opis strony głównej" : null,
    social_title: complete ? "Strona główna" : null,
    social_description: complete ? "Opis strony głównej" : null,
    fallback_fields: [],
    missing_fields: complete ? [] : ["translation"],
    complete,
    slug_locked: false,
  };
}

function fulfill(route: Route, json: unknown, status = 200) {
  return route.fulfill({ json, status });
}
